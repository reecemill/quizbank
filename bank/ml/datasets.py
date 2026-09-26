"""Public datasets, downloaded on first use and cached in a data directory.

Nothing here is committed to the repository: each dataset keeps its own
license and is fetched from its source.

* UNT Computer Science Short Answer dataset (Mohler & Mihalcea, 2011): answers
  from an intro computer science course, each scored 0-5 by two human graders.
  Cite: Michael Mohler, Razvan Bunescu, and Rada Mihalcea. "Learning to Grade
  Short Answer Questions using Semantic Similarity Measures and Dependency
  Graph Alignments." ACL 2011.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

UNT_URL = "http://web.eecs.umich.edu/~mihalcea/downloads/ShortAnswerGrading_v2.0.zip"
UNT_FILE = "ShortAnswerGrading_v2.0.zip"
EXAM_ASSIGNMENTS = {11, 12}  # graded 0-10 by each grader (see the dataset's README)


def default_data_dir() -> Path:
    return Path(os.environ.get("QUIZBANK_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


def download(url: str, path: Path) -> Path:
    """Fetch a URL to a file once, verifying certificates.

    Python checks against certifi's certificates, since some installs can't find
    the system ones. A few servers (including the UNT dataset's) leave out an
    intermediate certificate, which browsers and the system curl fill in but
    Python can't, so curl is the fallback. Certificate checks are never skipped.
    """
    if path.exists():
        return path
    import certifi

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        request = urllib.request.Request(url, headers={"User-Agent": "quizbank-ai"})
        with urllib.request.urlopen(request, context=context, timeout=120) as response:
            partial.write_bytes(response.read())
    except (urllib.error.URLError, ssl.SSLError) as error:
        curl = shutil.which("curl")
        result = subprocess.run([curl, "-fsSL", "--max-time", "300", "-o", str(partial), url],
                                capture_output=True) if curl else None
        if not result or result.returncode != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                f"Couldn't download {url} ({error}). Download it in a browser and save it as {path}."
            ) from error
    partial.rename(path)
    return path


def _lines_by_id(text: str) -> dict[str, str]:
    """'1.1 What is ...' lines -> {'1.1': 'What is ...'}."""
    result = {}
    for line in text.splitlines():
        match = re.match(r"^(\d+\.\d+)\s+(.*)$", line.strip())
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", text)).strip()


def parse_unt(archive: zipfile.ZipFile) -> pd.DataFrame:
    """One row per student answer: question_id, question, reference, answer,
    score (average of the two graders, 0-5), and each grader's score_1 and
    score_2 (also 0-5)."""
    root = next(name.split("data/")[0] for name in archive.namelist() if "data/raw/questions" in name)
    read = lambda name: archive.read(root + name).decode("latin-1")

    questions = _lines_by_id(read("data/raw/questions"))
    references = _lines_by_id(read("data/raw/answers"))
    ids = [line.strip() for line in read("data/docs/files").splitlines()
           if line.strip() and not line.startswith("#")]

    rows = []
    for qid in ids:
        answers = [_clean(line.split(" ", 1)[1] if line.startswith(qid + " ") else line)
                   for line in read(f"data/raw/{qid}").splitlines() if line.strip()]
        average = [float(x) for x in read(f"data/scores/{qid}/ave").split()]
        grader_1 = [float(x) for x in read(f"data/scores/{qid}/me").split()]
        grader_2 = [float(x) for x in read(f"data/scores/{qid}/other").split()]
        # The two exams (assignments 11 and 12) were graded 0-10 by each grader;
        # only the average was put on the 0-5 scale, so rescale the graders too.
        if int(qid.split(".")[0]) in EXAM_ASSIGNMENTS:
            grader_1, grader_2 = [x / 2 for x in grader_1], [x / 2 for x in grader_2]
        if not (len(answers) == len(average) == len(grader_1) == len(grader_2)):
            raise ValueError(f"Question {qid}: {len(answers)} answers but {len(average)} scores.")
        for answer, score, s1, s2 in zip(answers, average, grader_1, grader_2):
            rows.append({
                "question_id": qid,
                "question": _clean(questions[qid]),
                "reference": _clean(references[qid]),
                "answer": answer,
                "score": score,
                "score_1": s1,
                "score_2": s2,
            })
    return pd.DataFrame(rows)


def load_unt(data_dir: Path | None = None) -> pd.DataFrame:
    path = download(UNT_URL, (data_dir or default_data_dir()) / UNT_FILE)
    with zipfile.ZipFile(path) as archive:
        return parse_unt(archive)


def parse_unt_bytes(data: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return parse_unt(archive)
