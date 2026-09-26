# quizbank-ai

A question bank for instructors: import quizzes from Canvas, then search, de-duplicate, and tag questions with machine learning.

This is a rework of **QuizPress**, a CS senior design project. The original team built a Django app that converts Canvas quizzes into printable tests. This version keeps the part with the most lasting value, the Canvas importer and the question data model, and rebuilds it as a focused tool with ML features on top.

## Status

| Stage | What | Status |
|---|---|---|
| 1 | Clean foundation: Canvas QTI importer, data model, tests | ✅ Done |
| 2 | Smart question bank: semantic search, duplicate detection, auto-tagging, with evaluation | Next |
| 3 | LLM question generation, with an evaluation of output quality | Planned |
| 4 | Web UI and deployment | Core pages done; deployment planned |

## What works now

**Browse the bank in the browser.** Sign in at `http://127.0.0.1:8000/`. The design takes Canvas's structure (course cards on the dashboard, breadcrumbs, quiz questions laid out the way Canvas shows them) and draws it in a glass-and-glow style: a floating glass tab bar with a sliding highlight, glass panels over a slowly drifting color background, cards and rows that light up under the pointer, and the Geist font. Press ⌘K (Ctrl+K) anywhere to open a command palette that searches questions or jumps to a course. It follows the device's light or dark mode and works down to phone width.

- **Dashboard:** a card for each course.
- **Question bank:** every question, or one course's, with search and filters by question type.
- **Quizzes:** each quiz in order, with an **Answer key / Student view** switch.
- **Question pages:** the answer key, details, and the quizzes that use the question.
- **Import:** upload a Canvas export from the browser.

Editing is still done in the Django admin at `/admin/`.

**Import a Canvas quiz.** In Canvas, export a quiz as QTI (a `.zip`). Upload it on the Import page, or run:

```bash
python manage.py import_qti export.zip --course "CS 101" --course-name "Intro to Computing"
```

Supported question types: multiple choice, true/false, multiple selection, fill in the blank, and essay. Other types (matching, numerical, and so on) are imported with their text and flagged in a warning, so nothing is lost silently. Embedded images are extracted and saved with their question. Importing the same export into the same course twice is detected and skipped.

**Give a quiz to students, graded automatically.** On any quiz page, click **Give this quiz** to get a share link. Students open it, type their name, and take the quiz; no accounts needed. When they submit:

- Multiple choice and true/false get full points for the right answer.
- Multiple selection gets partial credit the way Canvas gives it: points are split across the right choices, each wrong choice takes a share back, and the score never drops below zero.
- Fill-in-the-blank answers match if they equal an accepted answer, ignoring capitalization and extra spaces.
- Essays wait for you. Grade them on each student's page and their score updates.

The results page shows every submission, the class average, how the class did on each question, and a CSV download. You choose whether students see the right answers after submitting, and you can close the link at any time. The page students take the quiz on never includes the answers; grading happens on the server.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DJANGO_DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py load_demo_data
python manage.py runserver
```

`DJANGO_DEBUG=1` is for local development only, and it lasts for the current terminal session. `load_demo_data` is optional: it adds three sample courses to explore the site with, and you can delete them in the admin afterwards.

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

Icons are from [Ionicons](https://ionic.io/ionicons) (MIT License). The [Geist](https://vercel.com/font) fonts are included under the SIL Open Font License (`bank/static/bank/fonts/OFL.txt`).
