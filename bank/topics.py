"""Topic tags for a course's questions: the database side.

Embeds each question (reusing cached embeddings when its text hasn't changed),
groups them with bank.ml.topics, and saves the topics and each question's tag.
"""

from __future__ import annotations

import hashlib

import numpy as np
from django.conf import settings
from django.db import transaction

from .ml.embeddings import embed, model_label
from .ml.topics import find_topics
from .models import Question, QuestionEmbedding, Topic

MIN_QUESTIONS = 10      # fewer than this and there's nothing to group
MAX_IN_BROWSER = 1500   # bigger courses use manage.py build_topics instead


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def question_vectors(questions: list[Question]) -> np.ndarray:
    """Embeddings for the questions, in order, computing only the missing or stale ones."""
    kind = settings.QUIZBANK_EMBEDDER
    label = model_label(kind)
    cached = {e.question_id: e for e in QuestionEmbedding.objects.filter(question__in=questions)}
    stale = [q for q in questions
             if q.pk not in cached or cached[q.pk].model != label or cached[q.pk].text_hash != _hash(q.text)]
    if stale:
        fresh = embed([q.text for q in stale], kind)
        for question, vector in zip(stale, fresh):
            QuestionEmbedding.objects.update_or_create(
                question=question,
                defaults={"model": label, "text_hash": _hash(question.text), "vector": vector.astype(np.float32).tobytes()},
            )
        cached = {e.question_id: e for e in QuestionEmbedding.objects.filter(question__in=questions)}
    return np.stack([np.frombuffer(bytes(cached[q.pk].vector), dtype=np.float32) for q in questions])


@transaction.atomic
def build_topics(course) -> list[Topic]:
    """Replace a course's topics with freshly found ones. Returns the new topics
    (none if the course is too small to group)."""
    questions = list(course.questions.order_by("pk"))
    course.topics.all().delete()  # questions' tags are cleared (SET_NULL)
    if len(questions) < MIN_QUESTIONS:
        return []

    result = find_topics([q.text for q in questions], question_vectors(questions))
    topics = {}
    for index in sorted(result.keywords):
        words = result.keywords[index]
        size = int((result.labels == index).sum())
        topics[index] = Topic.objects.create(
            course=course,
            label=" · ".join(words[:3]) if words else f"Topic {index + 1}",
            keywords=words,
            size=size,
        )
    for question, index in zip(questions, result.labels):
        question.topic = topics[int(index)]
    Question.objects.bulk_update(questions, ["topic"])
    return sorted(topics.values(), key=lambda t: (-t.size, t.label))
