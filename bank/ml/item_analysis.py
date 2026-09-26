"""Item analysis: how well each question on a test worked.

Classical test theory statistics, computed from a matrix of scores with one
row per student and one column per question. Each score is the fraction of
the question's points the student earned (0 to 1); NaN means not graded yet.

* Difficulty: the average score. High means easy.
* Discrimination: the item-rest correlation, i.e. the correlation between a
  question's score and the student's score on the *other* questions. Good
  questions are answered well by students who do well overall.
* Upper-lower index: average score in the top 27% of students minus the bottom
  27%, a simpler discrimination measure that's easy to explain.
* Reliability: Cronbach's alpha (equal to KR-20 when every question is
  right/wrong), and the standard error of measurement it implies.
* Options: for multiple-choice questions, which answers each group picked.

The flag thresholds follow common practice in the psychometrics literature
(e.g. Ebel & Frisbie, *Essentials of Educational Measurement*). The two flags
that point at a broken answer key also require the evidence to be significant
(a one-sided test at 5%), because in small classes the raw numbers swing a lot:
on simulated classes of 30 students this cut false alarms from 84% of flags to
22% (see notebooks/02_question_analytics.ipynb).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

GROUP_SHARE = 0.27          # top/bottom group size, the classic Kelley value
MIN_RELIABLE_STUDENTS = 20  # below this, the statistics are noisy

TOO_EASY = 0.90
TOO_HARD = 0.20
WEAK = 0.20
DEAD_OPTION = 0.05
STRONG_PICK_GAP = 0.05
Z_ONE_SIDED_5 = 1.645       # critical value for the significance checks


@dataclass
class Flag:
    code: str
    label: str
    severity: str  # "critical", "warning", or "info"


FLAGS = {
    "negative": Flag("negative", "Check the answer key", "critical"),
    "weak": Flag("weak", "Weak at telling students apart", "warning"),
    "too_hard": Flag("too_hard", "Very hard", "warning"),
    "too_easy": Flag("too_easy", "Very easy", "info"),
    "strong_pick": Flag("strong_pick", "Strong students pick this", "critical"),
    "dead": Flag("dead", "Almost nobody picks this", "info"),
}


@dataclass
class TestStatistics:
    n_students: int
    difficulty: np.ndarray        # per question, 0..1 (NaN if nobody graded)
    item_rest: np.ndarray         # per question, -1..1 (NaN if undefined)
    upper_lower: np.ndarray       # per question, -1..1
    alpha: float | None           # Cronbach's alpha over fully graded questions
    alpha_if_deleted: np.ndarray  # per question (NaN if not computable)
    sem: float | None             # standard error of measurement, in the scores' units
    totals: np.ndarray            # per student, sum of graded fractions
    top: np.ndarray = field(repr=False)     # boolean mask of the top group
    bottom: np.ndarray = field(repr=False)  # boolean mask of the bottom group


def cronbach_alpha(scores: np.ndarray) -> float | None:
    """Cronbach's alpha for a complete matrix (no NaN). None if undefined:
    fewer than two questions or students, or no spread in total scores."""
    n_students, n_items = scores.shape
    if n_items < 2 or n_students < 2:
        return None
    total_var = scores.sum(axis=1).var(ddof=1)
    if total_var == 0:
        return None
    item_vars = scores.var(axis=0, ddof=1).sum()
    return float(n_items / (n_items - 1) * (1 - item_vars / total_var))


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def groups(totals: np.ndarray, share: float = GROUP_SHARE) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks for the top and bottom groups by total score. Ties are
    broken by position, so both groups always have the same size."""
    n = len(totals)
    size = max(1, int(round(share * n))) if n >= 2 else 0
    order = np.argsort(totals, kind="stable")
    top, bottom = np.zeros(n, bool), np.zeros(n, bool)
    if size:
        bottom[order[:size]] = True
        top[order[-size:]] = True
    return top, bottom


def test_statistics(scores: np.ndarray, max_points: np.ndarray | None = None) -> TestStatistics:
    """Statistics for a students × questions matrix of scores (NaN = ungraded).

    Scores are points earned. Pass `max_points` (per question) to report
    difficulty as a fraction of each question's points; without it, scores are
    taken to be fractions already (for example 0/1)."""
    scores = np.asarray(scores, dtype=float)
    n_students, n_items = scores.shape
    scale = np.ones(n_items) if max_points is None else np.asarray(max_points, dtype=float)
    scale = np.where(scale > 0, scale, 1.0)
    graded = ~np.isnan(scores)
    filled = np.where(graded, scores, 0.0)
    totals = filled.sum(axis=1)
    top, bottom = groups(totals)

    difficulty = np.full(n_items, np.nan)
    item_rest = np.full(n_items, np.nan)
    upper_lower = np.full(n_items, np.nan)
    for j in range(n_items):
        rows = graded[:, j]
        if not rows.any():
            continue
        item = scores[rows, j]
        difficulty[j] = item.mean() / scale[j]
        rest = totals[rows] - item
        item_rest[j] = _pearson(item, rest)
        if top[rows].any() and bottom[rows].any():
            upper_lower[j] = (scores[top & rows, j].mean() - scores[bottom & rows, j].mean()) / scale[j]

    # Reliability uses the questions every student has a grade for.
    complete = graded.all(axis=0)
    alpha = cronbach_alpha(scores[:, complete]) if complete.sum() >= 2 else None
    alpha_if_deleted = np.full(n_items, np.nan)
    for j in np.flatnonzero(complete):
        keep = complete.copy()
        keep[j] = False
        if keep.sum() >= 2:
            value = cronbach_alpha(scores[:, keep])
            alpha_if_deleted[j] = np.nan if value is None else value
    sem = None
    if alpha is not None and n_students >= 2:
        sem = float(scores[:, complete].sum(axis=1).std(ddof=1) * np.sqrt(max(0.0, 1 - alpha)))

    return TestStatistics(n_students, difficulty, item_rest, upper_lower, alpha, alpha_if_deleted,
                          sem, totals, top, bottom)


def item_flags(difficulty: float, item_rest: float, n_students: int | None = None,
               adaptive: bool = True) -> list[Flag]:
    """Problems with one question, most serious first.

    With `adaptive` (the default) and a class size, a negative discrimination
    only raises "check the answer key" when it's significantly below zero;
    otherwise it counts as weak."""
    flags = []
    if not np.isnan(item_rest):
        negative_below = 0.0
        if adaptive and n_students:
            negative_below = -Z_ONE_SIDED_5 / np.sqrt(max(n_students - 3, 1))
        if item_rest < negative_below:
            flags.append(FLAGS["negative"])
        elif item_rest < WEAK:
            flags.append(FLAGS["weak"])
    if not np.isnan(difficulty):
        if difficulty > TOO_EASY:
            flags.append(FLAGS["too_easy"])
        elif difficulty < TOO_HARD:
            flags.append(FLAGS["too_hard"])
    return flags


@dataclass
class OptionStatistics:
    share_all: float
    share_top: float
    share_bottom: float
    flags: list[Flag]


def option_statistics(chosen: np.ndarray, is_correct: bool, top: np.ndarray,
                      bottom: np.ndarray, adaptive: bool = True) -> OptionStatistics:
    """How often one answer option was picked, overall and by group.
    `chosen` is a boolean per student: did they pick this option?

    With `adaptive`, "strong students pick this" needs the top group's lead to
    be significant for the group size, not just 5 points."""
    chosen = np.asarray(chosen, bool)
    share_all = float(chosen.mean()) if len(chosen) else 0.0
    share_top = float(chosen[top].mean()) if top.any() else 0.0
    share_bottom = float(chosen[bottom].mean()) if bottom.any() else 0.0
    flags = []
    if not is_correct:
        # A wrong answer that attracts strong students more than weak ones is
        # usually a second right answer, or the key is wrong.
        needed = STRONG_PICK_GAP
        if adaptive and top.any():
            pooled = (share_top + share_bottom) / 2
            standard_error = np.sqrt(max(pooled * (1 - pooled), 1e-9) * 2 / top.sum())
            needed = max(needed, Z_ONE_SIDED_5 * standard_error)
        if share_top - share_bottom >= needed:
            flags.append(FLAGS["strong_pick"])
        if share_all < DEAD_OPTION:
            flags.append(FLAGS["dead"])
    return OptionStatistics(share_all, share_top, share_bottom, flags)


def reliability_rating(alpha: float | None) -> str:
    """A plain-language rating for Cronbach's alpha (George & Mallery's bands)."""
    if alpha is None:
        return "Not enough data"
    if alpha >= 0.9:
        return "Excellent"
    if alpha >= 0.8:
        return "Good"
    if alpha >= 0.7:
        return "Acceptable"
    if alpha >= 0.6:
        return "Questionable"
    return "Poor"
