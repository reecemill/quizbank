"""Item analysis for a quiz given to students: the database side.

Builds the students × questions score matrix for an assignment, runs the
statistics in bank.ml.item_analysis on it, and packages the results (and the
score histogram's geometry) for the analytics page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .grading import CHOICE_TYPES
from .ml import item_analysis as ia
from .models import Response


@dataclass
class OptionRow:
    text: str
    is_correct: bool
    share_all: int      # percent
    share_top: int
    share_bottom: int
    flags: list[ia.Flag]


@dataclass
class ItemRow:
    number: int
    question: object
    graded: int                    # students with a grade for this question
    difficulty: int | None         # percent of points earned
    discrimination: float | None   # item-rest correlation
    upper_lower: float | None
    alpha_if_deleted: float | None
    flags: list[ia.Flag]
    options: list[OptionRow] = field(default_factory=list)

    @property
    def all_flags(self) -> list[ia.Flag]:
        """The question's flags, then its options' (each kind once)."""
        seen, flags = set(), []
        for flag in self.flags + [f for o in self.options for f in o.flags]:
            if flag.code not in seen:
                seen.add(flag.code)
                flags.append(flag)
        return flags

    @property
    def discrimination_width(self) -> float:
        """Half-width share of the diverging bar, 0..50 (percent of the track)."""
        return 0.0 if self.discrimination is None else min(1.0, abs(self.discrimination)) * 50

    @property
    def worst_severity(self) -> str | None:
        severities = [f.severity for f in self.flags] + [f.severity for o in self.options for f in o.flags]
        for level in ("critical", "warning", "info"):
            if level in severities:
                return level
        return None


@dataclass
class HistogramBar:
    label: str      # "70–79%"
    tick: str       # the bin's lower edge, for the axis: "70"
    count: int
    height: float   # percent of the plot height


@dataclass
class Histogram:
    bars: list[HistogramBar]
    ticks: list[tuple[int, float]]  # (count, percent of plot height)


@dataclass
class Report:
    n_students: int
    items: list[ItemRow]
    alpha: float | None
    alpha_rating: str
    sem_points: float | None
    average_percent: int | None
    pending_answers: int
    histogram: Histogram | None

    @property
    def reliable(self) -> bool:
        return self.n_students >= ia.MIN_RELIABLE_STUDENTS

    @property
    def flagged(self) -> list[ItemRow]:
        return [item for item in self.items if item.worst_severity in ("critical", "warning")]


def _clean(value) -> float | None:
    return None if value is None or np.isnan(value) else float(value)


def analyze_assignment(assignment) -> Report:
    items = list(assignment.test.items.select_related("question").prefetch_related("question__options"))
    attempts = list(assignment.attempts.order_by("pk"))
    row_of = {attempt.pk: i for i, attempt in enumerate(attempts)}
    col_of = {item.question_id: j for j, item in enumerate(items)}

    scores = np.full((len(attempts), len(items)), np.nan)
    for attempt_id, question_id, points in Response.objects.filter(attempt__assignment=assignment).values_list(
        "attempt_id", "question_id", "points"
    ):
        if question_id in col_of and points is not None:
            scores[row_of[attempt_id], col_of[question_id]] = float(points)

    chosen: dict[int, set[tuple[int, int]]] = {}  # option id -> {(student row)}
    through = Response.selected.through.objects.filter(response__attempt__assignment=assignment)
    for attempt_id, option_id in through.values_list("response__attempt_id", "answeroption_id"):
        chosen.setdefault(option_id, set()).add(row_of[attempt_id])

    max_points = np.array([float(item.question.points) for item in items])
    pending = int(np.isnan(scores).sum()) if attempts else 0

    if not attempts:
        return Report(0, [], None, ia.reliability_rating(None), None, None, 0, None)

    stats = ia.test_statistics(scores, max_points)
    rows = []
    for j, item in enumerate(items):
        question = item.question
        graded = int((~np.isnan(scores[:, j])).sum())
        difficulty = _clean(stats.difficulty[j])
        discrimination = _clean(stats.item_rest[j])
        row = ItemRow(
            number=j + 1,
            question=question,
            graded=graded,
            difficulty=None if difficulty is None else round(difficulty * 100),
            discrimination=discrimination,
            upper_lower=_clean(stats.upper_lower[j]),
            alpha_if_deleted=_clean(stats.alpha_if_deleted[j]),
            flags=ia.item_flags(stats.difficulty[j], stats.item_rest[j], len(attempts)),
        )
        if question.question_type in CHOICE_TYPES:
            for option in question.options.all():
                picked = np.zeros(len(attempts), bool)
                picked[list(chosen.get(option.pk, ()))] = True
                o = ia.option_statistics(picked, option.is_correct, stats.top, stats.bottom)
                row.options.append(OptionRow(
                    text=option.text,
                    is_correct=option.is_correct,
                    share_all=round(o.share_all * 100),
                    share_top=round(o.share_top * 100),
                    share_bottom=round(o.share_bottom * 100),
                    flags=o.flags,
                ))
        rows.append(row)

    percents = [attempt.percent for attempt in attempts]
    return Report(
        n_students=len(attempts),
        items=rows,
        alpha=stats.alpha,
        alpha_rating=ia.reliability_rating(stats.alpha),
        sem_points=stats.sem,
        average_percent=round(sum(percents) / len(percents)),
        pending_answers=pending,
        histogram=histogram(percents),
    )


def histogram(percents: list[int], bins: int = 10) -> Histogram:
    """Bars for a score histogram in 10-point bins (the last one includes 100),
    scaled to a round axis maximum with about four gridlines."""
    counts = [0] * bins
    for value in percents:
        counts[min(int(value // (100 / bins)), bins - 1)] += 1
    peak = max(counts) or 1
    step = max(1, int(np.ceil(peak / 4)))
    axis_max = step * int(np.ceil(peak / step))

    bars = []
    for i, count in enumerate(counts):
        low = i * 100 // bins
        high = 100 if i == bins - 1 else low + 100 // bins - 1
        bars.append(HistogramBar(f"{low}–{high}%", str(low), count, count / axis_max * 100))
    ticks = [(value, value / axis_max * 100) for value in range(0, axis_max + 1, step)]
    return Histogram(bars, ticks)
