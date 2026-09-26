"""Suggesting scores for written answers.

The task: given a question, the instructor's model answer, and a student's
answer, predict the 0-5 score human graders would give. The model never sees
the question in training (evaluation is split by question), because in the app
every question it grades is new to it. So it learns from question-agnostic
signals: how close the answer is to the model answer in meaning and in words,
how much of the model answer it covers, and how long it is.

Features (see `FeatureBuilder`):

* emb_sim: cosine similarity of sentence embeddings, answer vs model answer
* emb_q_sim: the same, answer vs the question (answers that only restate the
  question score low)
* tfidf_sim: TF-IDF cosine similarity, answer vs model answer
* recall: share of the model answer's content words the answer uses
* precision: share of the answer's content words found in the model answer
* log_len, len_ratio: answer length, and length relative to the model answer

Evaluated in notebooks/01_essay_grading.ipynb on the UNT dataset (bank.ml.datasets).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics import cohen_kappa_score, mean_absolute_error, mean_squared_error

from .embeddings import embed, model_label

MAX_SCORE = 5.0
FEATURES = ["emb_sim", "emb_q_sim", "tfidf_sim", "recall", "precision", "log_len", "len_ratio"]


def content_words(text: str) -> set[str]:
    """Lowercased words minus stop words, with a crude suffix strip so that
    'variables' and 'variable' match."""
    words = re.findall(r"[a-z0-9+#]+", text.lower())
    return {re.sub(r"(ing|ed|es|s)$", "", w) or w for w in words if w not in ENGLISH_STOP_WORDS}


@dataclass
class FeatureBuilder:
    """Turns (question, reference, answer) rows into the feature table.
    `fit` learns TF-IDF weights from training text only."""

    embedder: str = "minilm"
    tfidf: TfidfVectorizer | None = None

    def fit(self, df: pd.DataFrame) -> "FeatureBuilder":
        corpus = pd.concat([df["answer"], df["reference"].drop_duplicates()])
        self.tfidf = TfidfVectorizer(sublinear_tf=True, stop_words="english", min_df=1).fit(corpus)
        return self

    def transform(self, df: pd.DataFrame, embeddings: dict[str, np.ndarray] | None = None) -> pd.DataFrame:
        vectors = embeddings or embed_texts(df, self.embedder)
        answer, reference, question = (np.stack([vectors[t] for t in df[col]])
                                       for col in ("answer", "reference", "question"))
        a_tfidf, r_tfidf = self.tfidf.transform(df["answer"]), self.tfidf.transform(df["reference"])
        tfidf_sim = np.asarray(a_tfidf.multiply(r_tfidf).sum(axis=1)).ravel()

        recall, precision = [], []
        for ans, ref in zip(df["answer"], df["reference"]):
            a, r = content_words(ans), content_words(ref)
            recall.append(len(a & r) / len(r) if r else 0.0)
            precision.append(len(a & r) / len(a) if a else 0.0)
        a_len = df["answer"].str.split().str.len().fillna(0).to_numpy(float)
        r_len = df["reference"].str.split().str.len().fillna(0).to_numpy(float)
        return pd.DataFrame({
            "emb_sim": (answer * reference).sum(axis=1),
            "emb_q_sim": (answer * question).sum(axis=1),
            "tfidf_sim": tfidf_sim,
            "recall": recall,
            "precision": precision,
            "log_len": np.log1p(a_len),
            "len_ratio": np.log1p(a_len) - np.log1p(r_len),
        }, index=df.index)


def embed_texts(df: pd.DataFrame, embedder: str = "minilm") -> dict[str, np.ndarray]:
    """Embed every distinct question, reference, and answer once."""
    texts = list(dict.fromkeys(pd.concat([df["question"], df["reference"], df["answer"]]).tolist()))
    return dict(zip(texts, embed(texts, embedder)))


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def metrics(true: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Pearson r, RMSE, MAE, and quadratic weighted kappa on whole-point scores."""
    true, predicted = np.asarray(true, float), np.clip(np.asarray(predicted, float), 0, MAX_SCORE)
    r = pearsonr(true, predicted)[0] if np.ptp(predicted) > 1e-9 and np.ptp(true) > 0 else 0.0
    return {
        "pearson": float(r),
        "rmse": float(np.sqrt(mean_squared_error(true, predicted))),
        "mae": float(mean_absolute_error(true, predicted)),
        "qwk": float(cohen_kappa_score(np.rint(true).astype(int), np.rint(predicted).astype(int),
                                       weights="quadratic", labels=list(range(6)))),
    }


# --------------------------------------------------------------------------
# The trained grader used by the app
# --------------------------------------------------------------------------

@dataclass
class EssayGrader:
    builder: FeatureBuilder
    model: object
    evaluation: dict = field(default_factory=dict)  # cross-validated metrics, shown in the app

    def predict_scores(self, questions: list[str], references: list[str], answers: list[str]) -> np.ndarray:
        """Predicted 0-5 scores. Blank answers get 0 without asking the model."""
        df = pd.DataFrame({"question": questions, "reference": references, "answer": answers})
        features = self.builder.transform(df)
        scores = np.clip(self.model.predict(features[FEATURES]), 0, MAX_SCORE)
        blank = df["answer"].str.strip().eq("").to_numpy()
        scores[blank] = 0.0
        return scores

    def save(self, path: Path) -> None:
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "EssayGrader":
        import joblib

        return joblib.load(path)


FINAL_MODEL = "All features, ridge"  # chosen by cross-validation in notebook 01


def make_model():
    """The production model: standardized features into ridge regression. It beat
    gradient boosting on held-out questions (see notebook 01)."""
    return _ridge(FEATURES)[1]


def make_boosting():
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                         min_samples_leaf=20, l2_regularization=1.0, random_state=0)


def train(df: pd.DataFrame, embedder: str = "minilm", evaluation: dict | None = None) -> EssayGrader:
    """Fit the final grader on all of `df`."""
    embeddings = embed_texts(df, embedder)
    builder = FeatureBuilder(embedder=embedder).fit(df)
    features = builder.transform(df, embeddings)
    model = make_model().fit(features[FEATURES], df["score"])
    info = {"embedder": model_label(embedder), "trained_on": len(df), **(evaluation or {})}
    return EssayGrader(builder, model, info)


def scale_to_points(score: float, points: float) -> float:
    """A 0-5 prediction as a question's points, rounded to the nearest half point."""
    return round(score / MAX_SCORE * points * 2) / 2


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def _ridge(columns):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return columns, make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def candidate_models() -> dict[str, tuple[list[str] | None, object]]:
    """The baselines and models compared, simplest first. (None = no features.)"""
    return {
        "Average score": (None, None),
        "Length only": _ridge(["log_len", "len_ratio"]),
        "Word overlap (TF-IDF)": _ridge(["tfidf_sim"]),
        "Meaning (embeddings)": _ridge(["emb_sim"]),
        "All features, ridge": _ridge(FEATURES),
        "All features, gradient boosting": (FEATURES, make_boosting()),
    }


def cross_validate(df: pd.DataFrame, embedder: str = "minilm", n_splits: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Grouped K-fold by question: every fold's test questions are unseen in training.

    Returns (per-fold metrics, out-of-fold predictions for every model)."""
    from sklearn.base import clone
    from sklearn.model_selection import GroupKFold

    embeddings = embed_texts(df, embedder)
    fold_rows, predictions = [], pd.DataFrame(index=df.index)
    for fold, (train_idx, test_idx) in enumerate(GroupKFold(n_splits=n_splits).split(df, groups=df["question_id"])):
        train_df, test_df = df.iloc[train_idx], df.iloc[test_idx]
        builder = FeatureBuilder(embedder=embedder).fit(train_df)
        train_x, test_x = builder.transform(train_df, embeddings), builder.transform(test_df, embeddings)
        for name, (columns, model) in candidate_models().items():
            if columns is None:
                predicted = np.full(len(test_df), train_df["score"].mean())
            else:
                fitted = clone(model).fit(train_x[columns], train_df["score"])
                predicted = np.clip(fitted.predict(test_x[columns]), 0, MAX_SCORE)
            predictions.loc[test_df.index, name] = predicted
            fold_rows.append({"model": name, "fold": fold, **metrics(test_df["score"], predicted)})
    return pd.DataFrame(fold_rows), predictions


def human_agreement(df: pd.DataFrame) -> dict[str, float]:
    """How well the two graders agree with each other: the practical ceiling."""
    return metrics(df["score_1"], df["score_2"])
