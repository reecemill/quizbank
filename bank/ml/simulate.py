"""Simulated classes, for checking item analysis against known answers.

Real class data never says which questions are actually flawed, so the flags
in item_analysis are tested on simulated students instead, where the truth is
known.

Each student has an ability theta drawn from N(0, 1). Each multiple-choice
question follows the three-parameter logistic (3PL) IRT model:

    P(right | theta) = c + (1 - c) / (1 + exp(-a (theta - b)))

where b is the difficulty, a the discrimination, and c the chance of guessing
right. A student who doesn't get it right picks a wrong option in proportion
to how attractive each one is.

Problems can be planted on purpose:

* "miskeyed": the answer key marks one option, but the real right answer is
  another. Strong students pick the real one and get marked wrong.
* "dead": one wrong option that nobody finds plausible.
* "easy": a question far below the class's level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .item_analysis import (DEAD_OPTION, TOO_EASY, option_statistics, item_flags,
                            test_statistics)

PROBLEMS = ("miskeyed", "dead", "easy")


@dataclass
class SimQuestion:
    a: float                 # discrimination
    b: float                 # difficulty
    c: float                 # guessing
    n_options: int
    marked_key: int          # the option the answer key says is right
    true_key: int            # the option that's actually right
    attract: np.ndarray      # how attractive each option is as a wrong pick
    planted: set[str] = field(default_factory=set)


def expit(x):
    return 1 / (1 + np.exp(-x))


def make_questions(n_questions: int, rng: np.random.Generator, n_options: int = 4,
                   plant: tuple[str, ...] = PROBLEMS, guessing: bool = True) -> list[SimQuestion]:
    """Random question parameters, with each problem in `plant` put on its own question."""
    if len(plant) > n_questions:
        raise ValueError("More planted problems than questions.")
    questions = []
    for _ in range(n_questions):
        key = int(rng.integers(n_options))
        questions.append(SimQuestion(
            a=float(rng.lognormal(0.0, 0.3)),
            b=float(rng.normal(0.0, 1.0)),
            c=(1 / n_options) * 0.8 if guessing else 0.0,
            n_options=n_options,
            marked_key=key,
            true_key=key,
            # Wrong options differ in how tempting they are, but none is dead.
            attract=rng.dirichlet(np.full(n_options, 4.0)),
        ))

    for problem, index in zip(plant, rng.choice(n_questions, size=len(plant), replace=False)):
        q = questions[index]
        wrong = [o for o in range(n_options) if o != q.marked_key]
        if problem == "miskeyed":
            q.true_key = int(rng.choice(wrong))
            q.b = float(rng.normal(-0.5, 0.5))  # the real answer is reasonably well known
        elif problem == "dead":
            q.attract[int(rng.choice(wrong))] = 0.003
        elif problem == "easy":
            q.b = -3.0
        q.planted.add(problem)
    return questions


@dataclass
class SimClass:
    theta: np.ndarray    # ability per student
    choices: np.ndarray  # option picked, students × questions
    scores: np.ndarray   # 1 if the pick matches the answer key, else 0


def simulate_class(questions: list[SimQuestion], n_students: int, rng: np.random.Generator) -> SimClass:
    theta = rng.normal(0.0, 1.0, n_students)
    choices = np.empty((n_students, len(questions)), dtype=int)
    for j, q in enumerate(questions):
        p_right = q.c + (1 - q.c) * expit(q.a * (theta - q.b))
        right = rng.random(n_students) < p_right
        weights = q.attract.copy()
        weights[q.true_key] = 0
        wrong_pick = rng.choice(q.n_options, size=n_students, p=weights / weights.sum())
        choices[:, j] = np.where(right, q.true_key, wrong_pick)
    keys = np.array([q.marked_key for q in questions])
    return SimClass(theta, choices, (choices == keys).astype(float))


# --------------------------------------------------------------------------
# What the flags *should* say, from the true parameters
# --------------------------------------------------------------------------

_GRID = np.linspace(-6, 6, 601)
_WEIGHTS = np.exp(-_GRID ** 2 / 2)
_WEIGHTS /= _WEIGHTS.sum()


def expected_shares(q: SimQuestion) -> np.ndarray:
    """How often each option is picked across the whole population of students."""
    p_right = q.c + (1 - q.c) * expit(q.a * (_GRID - q.b))
    weights = q.attract.copy()
    weights[q.true_key] = 0
    weights = weights / weights.sum()
    shares = np.outer(1 - p_right, weights)
    shares[:, q.true_key] += p_right
    return _WEIGHTS @ shares


def true_flags(q: SimQuestion) -> set[str]:
    """The flags a perfect analysis of an infinitely large class would raise."""
    shares = expected_shares(q)
    truth = set()
    if q.true_key != q.marked_key:
        truth.add("miskeyed")
    if shares[q.marked_key] > TOO_EASY:
        truth.add("easy")
    if any(shares[o] < DEAD_OPTION for o in range(q.n_options) if o != q.marked_key):
        truth.add("dead")
    return truth


def detected_flags(sim: SimClass, questions: list[SimQuestion], adaptive: bool = True) -> list[set[str]]:
    """What item analysis flags on one simulated class, in the same terms as true_flags."""
    stats = test_statistics(sim.scores)
    n_students = sim.scores.shape[0]
    found = []
    for j, q in enumerate(questions):
        codes = {flag.code for flag in item_flags(stats.difficulty[j], stats.item_rest[j], n_students, adaptive)}
        for o in range(q.n_options):
            option = option_statistics(sim.choices[:, j] == o, o == q.marked_key, stats.top, stats.bottom, adaptive)
            codes |= {flag.code for flag in option.flags}
        result = set()
        if codes & {"negative", "strong_pick"}:
            result.add("miskeyed")
        if "too_easy" in codes:
            result.add("easy")
        if "dead" in codes:
            result.add("dead")
        found.append(result)
    return found


def flag_accuracy(n_tests: int, n_students: int, n_questions: int = 20, seed: int = 0,
                  adaptive: bool = True) -> dict[str, dict]:
    """Precision and recall of each flag over many simulated tests.

    Every test gets one planted problem of each kind, and the truth for each
    question comes from its real parameters (see true_flags), so a question
    that is naturally very easy counts as a correct "easy" flag, not a false alarm.
    """
    rng = np.random.default_rng(seed)
    counts = {problem: {"tp": 0, "fp": 0, "fn": 0} for problem in PROBLEMS}
    for _ in range(n_tests):
        questions = make_questions(n_questions, rng)
        sim = simulate_class(questions, n_students, rng)
        for q, found in zip(questions, detected_flags(sim, questions, adaptive)):
            truth = true_flags(q)
            for problem in PROBLEMS:
                if problem in found and problem in truth:
                    counts[problem]["tp"] += 1
                elif problem in found:
                    counts[problem]["fp"] += 1
                elif problem in truth:
                    counts[problem]["fn"] += 1
    results = {}
    for problem, c in counts.items():
        flagged, actual = c["tp"] + c["fp"], c["tp"] + c["fn"]
        results[problem] = {
            **c,
            "precision": c["tp"] / flagged if flagged else float("nan"),
            "recall": c["tp"] / actual if actual else float("nan"),
        }
    return results
