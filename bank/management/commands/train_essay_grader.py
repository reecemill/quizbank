"""Train the model that suggests scores for written answers.

Downloads the UNT short-answer dataset (about 1.4 MB) and the sentence
embedding model (about 90 MB) on first run, measures the model with
question-grouped cross-validation, then trains it on everything and saves it
to QUIZBANK_DATA_DIR/essay_grader.joblib. Takes about a minute on a laptop.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from bank.ml import datasets
from bank.ml import essay_grader as eg

GRADER_FILE = "essay_grader.joblib"


class Command(BaseCommand):
    help = "Train the written-answer grading model on the UNT short-answer dataset."

    def handle(self, *args, **options):
        data_dir = settings.QUIZBANK_DATA_DIR
        embedder = settings.QUIZBANK_EMBEDDER
        self.stdout.write("Loading the UNT short-answer dataset...")
        df = datasets.load_unt(data_dir)
        self.stdout.write(f"{len(df)} answers to {df['question_id'].nunique()} questions. Cross-validating...")

        folds, predictions = eg.cross_validate(df, embedder)
        held_out = eg.metrics(df["score"], predictions[eg.FINAL_MODEL])
        humans = eg.human_agreement(df)
        evaluation = {"pearson": held_out["pearson"], "qwk": held_out["qwk"], "mae": held_out["mae"],
                      "human_pearson": humans["pearson"], "questions": int(df["question_id"].nunique())}

        grader = eg.train(df, embedder, evaluation)
        path = data_dir / GRADER_FILE
        grader.save(path)
        self.stdout.write(self.style.SUCCESS(
            f"Saved {path}. On questions it never saw: r = {held_out['pearson']:.2f} with the human graders "
            f"(two humans agree at r = {humans['pearson']:.2f}), average error {held_out['mae']:.2f} of 5 points."
        ))
