"""Grouping questions into topics, without labels.

The app's method: embed each question (bank.ml.embeddings), cluster the vectors
with k-means, pick the number of topics k by silhouette score, and name each
cluster by its most distinctive words using class-based TF-IDF (the labeling
step BERTopic uses). The alternatives here (TF-IDF + k-means, LDA, HDBSCAN)
are the baselines it's compared against in notebooks/03_topic_tags.ipynb, on
MMLU questions whose true subjects are known.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TOKEN_PATTERN = r"(?u)\b[a-zA-Z][a-zA-Z]{2,}\b"  # words of 3+ letters

# Words that show up in quiz questions of every subject ("Which of the following
# statements best describes...") and make poor topic names.
QUESTION_WORDS = {
    "according", "answer", "best", "called", "choose", "correct", "describe", "describes", "does",
    "example", "explain", "false", "following", "given", "true", "known", "likely", "question",
    "questions", "select", "statement", "statements", "term", "used", "uses", "using", "way", "ways",
    "type", "types", "refers", "refer", "important", "main", "use", "different", "called",
}


def _stop_words() -> list[str]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    return sorted(ENGLISH_STOP_WORDS | QUESTION_WORDS)


@dataclass
class TopicResult:
    labels: np.ndarray               # topic index per question
    k: int
    keywords: dict[int, list[str]]   # topic index -> its top words
    silhouettes: dict[int, float]    # k -> silhouette score, for each k tried


def kmeans(vectors: np.ndarray, k: int, seed: int = 0) -> np.ndarray:
    from sklearn.cluster import KMeans

    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(vectors)


def choose_k(vectors: np.ndarray, k_min: int = 2, k_max: int = 15, seed: int = 0,
             sample: int = 3000) -> tuple[int, dict[int, float]]:
    """The k with the best silhouette score (cosine distance). Scores are computed
    on a sample of up to `sample` questions to stay fast on big banks."""
    from sklearn.metrics import silhouette_score

    n = len(vectors)
    k_max = max(k_min, min(k_max, n - 1))
    scores = {}
    for k in range(k_min, k_max + 1):
        labels = kmeans(vectors, k, seed)
        if len(set(labels)) < 2:
            continue
        scores[k] = float(silhouette_score(vectors, labels, metric="cosine",
                                           sample_size=min(sample, n), random_state=seed))
    best = max(scores, key=scores.get) if scores else 1
    return best, scores


def label_clusters(texts: list[str], labels: np.ndarray, top_n: int = 3) -> dict[int, list[str]]:
    """Top words per cluster by class-based TF-IDF: a word scores high when it's
    frequent in this cluster and rare across the others.

        score(t, c) = tf(t, c) * log(1 + A / f(t))

    where tf is the word's share of the cluster's words, A the average number of
    words per cluster, and f(t) the word's frequency across all clusters."""
    from sklearn.feature_extraction.text import CountVectorizer

    clusters = sorted(set(int(label) for label in labels))
    documents = [" ".join(t for t, label in zip(texts, labels) if label == c) for c in clusters]
    vectorizer = CountVectorizer(stop_words=_stop_words(), token_pattern=TOKEN_PATTERN)
    try:
        counts = vectorizer.fit_transform(documents).toarray().astype(float)
    except ValueError:  # no words left at all
        return {c: [] for c in clusters}
    if counts.size == 0:
        return {c: [] for c in clusters}
    words = vectorizer.get_feature_names_out()
    tf = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    idf = np.log(1 + counts.sum(axis=1).mean() / np.maximum(counts.sum(axis=0), 1))
    scores = tf * idf
    return {c: [words[i] for i in np.argsort(-scores[row])[:top_n] if scores[row, i] > 0]
            for row, c in enumerate(clusters)}


def find_topics(texts: list[str], vectors: np.ndarray, k_max: int = 15, seed: int = 0) -> TopicResult:
    """The app's method: embeddings + k-means with k chosen by silhouette + c-TF-IDF labels."""
    k_max = min(k_max, max(2, len(texts) // 4))
    k, scores = choose_k(vectors, 2, k_max, seed)
    labels = kmeans(vectors, k, seed)
    return TopicResult(labels, k, label_clusters(texts, labels), scores)


# --------------------------------------------------------------------------
# Baselines, for the evaluation notebook
# --------------------------------------------------------------------------

def tfidf_kmeans(texts: list[str], k: int, seed: int = 0) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectors = TfidfVectorizer(stop_words="english", token_pattern=TOKEN_PATTERN, sublinear_tf=True).fit_transform(texts)
    return kmeans(vectors, k, seed)


def lda(texts: list[str], k: int, seed: int = 0) -> np.ndarray:
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    counts = CountVectorizer(stop_words="english", token_pattern=TOKEN_PATTERN, min_df=2).fit_transform(texts)
    model = LatentDirichletAllocation(n_components=k, learning_method="batch", max_iter=30, random_state=seed)
    return model.fit_transform(counts).argmax(axis=1)


def hdbscan(vectors: np.ndarray, min_cluster_size: int = 15) -> np.ndarray:
    """Density-based clusters; questions that fit none get -1 (noise)."""
    from sklearn.cluster import HDBSCAN

    return HDBSCAN(min_cluster_size=min_cluster_size, metric="cosine").fit_predict(vectors)
