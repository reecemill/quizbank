# quizbank-ai

A question bank for instructors: import quizzes from Canvas, then search, de-duplicate, and tag questions with machine learning.

This is a rework of **QuizPress**, a CS senior design project. The original team built a Django app that converts Canvas quizzes into printable tests. This version keeps the part with the most lasting value, the Canvas importer and the question data model, and rebuilds it as a focused tool with ML features on top.

## Status

| Stage | What | Status |
|---|---|---|
| 1 | Clean foundation: Canvas QTI importer, data model, tests | ✅ Done |
| 2 | Smart question bank: semantic search, duplicate detection, auto-tagging, with evaluation | Next |
| 3 | LLM question generation, with an evaluation of output quality | Planned |
| 4 | Web UI and deployment | Planned |

## What works now

**Import a Canvas quiz.** In Canvas, export a quiz as QTI (a `.zip`), then:

```bash
python manage.py import_qti export.zip --course "CS 101" --course-name "Intro to Computing"
```

Supported question types: multiple choice, true/false, multiple selection, fill in the blank, and essay. Other types (matching, numerical, and so on) are imported with their text and flagged in a warning, so nothing is lost silently. Embedded images are extracted and saved with their question. Importing the same export into the same course twice is detected and skipped.

Browse and edit the imported questions in the Django admin at `/admin/`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DJANGO_DEBUG=1          # local development only
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Settings come from environment variables; see `.env.example`. Outside of debug mode the app refuses to start without `DJANGO_SECRET_KEY`.

## Tests

```bash
DJANGO_DEBUG=1 python manage.py test bank
```

The tests build Canvas-style exports in memory, so no sample files or network access are needed.

## What changed from QuizPress

- **The importer is now a standalone module** (`bank/qti.py`) with no Django dependency, covered by tests.
- **Import bugs fixed:**
  - Question metadata is read by label rather than by position, so exports with fields in a different order still import.
  - The importer no longer sets fields that don't exist on the model, which crashed every import.
  - Correct answers come from the scoring rule, not from Canvas's per-answer feedback rules.
- **Imports are all-or-nothing.** A bad file writes nothing to the database.
- **No secrets in the code.** Credentials and keys come from environment variables. Uploaded XML is parsed with `defusedxml`.
- **Slimmed down.** The publisher, template, cover-page, and feedback features and their dashboards were dropped to make room for the ML work.

## Credits

QuizPress was built by the SPG8 senior design team: Amadeus Grimm, garynino, dafearn, and Reece Milligan. The original data model and Canvas importer this project builds on are their work. Original repository: [dafearn/SPG8fearn](https://github.com/dafearn/SPG8fearn).

The rework is by Reece Milligan.
