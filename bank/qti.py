"""Parse Canvas "Classic Quiz" QTI 1.2 exports.

This module is plain Python with no Django imports, so it can be tested and
reused on its own. It turns a Canvas export zip into dataclasses; saving them
to the database is `bank.importer`'s job.

Rewritten from the SPG8 importer. The changes that matter:

* Question type and points are read from metadata by *label*, not by position,
  so exports whose fields come in a different order still parse.
* The correct answer is the response condition that sets SCORE to 100, rather
  than any condition marked ``continue="No"``.
* The questions file and its metadata are found by content (the root element),
  not by assuming a sort order of file names inside each folder.
* Unsupported question types are kept (as OTHER, with their text) and reported
  as warnings, instead of being silently dropped.
* XML is parsed with defusedxml, because these files are user uploads.

Canvas export layout, for reference::

    export.zip
      imsmanifest.xml
      <quiz id>/assessment_meta.xml   quiz title and description
      <quiz id>/<quiz id>.xml         the questions (<questestinterop>)
      web_resources/Quiz Files/...    images referenced by questions
"""

from __future__ import annotations

import re
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import BinaryIO
from xml.etree.ElementTree import Element

from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeET

# Canvas type name -> our Question.Type code.
QUESTION_TYPES = {
    "multiple_choice_question": "MC",
    "true_false_question": "TF",
    "multiple_answers_question": "MS",
    "short_answer_question": "FB",  # Canvas calls fill-in-the-blank "short answer"
    "essay_question": "ES",
}

# Not questions at all: text blocks between questions. Skipped, not stored.
NON_QUESTION_TYPES = {"text_only_question"}

IMAGE_PREFIX = "$IMS-CC-FILEBASE$/"


class QTIError(ValueError):
    """The upload isn't a readable Canvas QTI export."""


@dataclass
class ParsedOption:
    text: str
    is_correct: bool


@dataclass
class ParsedImage:
    filename: str
    data: bytes


@dataclass
class ParsedQuestion:
    ident: str
    source_type: str
    question_type: str  # one of Question.Type's codes
    text: str
    text_html: str
    points: float
    options: list[ParsedOption] = field(default_factory=list)
    image: ParsedImage | None = None


@dataclass
class ParsedAssessment:
    ident: str
    title: str
    instructions: str
    questions: list[ParsedQuestion] = field(default_factory=list)


@dataclass
class ParseResult:
    assessments: list[ParsedAssessment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def question_count(self) -> int:
        return sum(len(a.questions) for a in self.assessments)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _strip_namespaces(root: Element) -> Element:
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _parse_xml(data: bytes) -> Element:
    try:
        return _strip_namespaces(SafeET.fromstring(data))
    except SafeET.ParseError as exc:
        raise QTIError(f"Malformed XML: {exc}") from exc


def html_to_text(html: str) -> str:
    """Plain text from a Canvas HTML fragment, whitespace collapsed."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _mattext(elem: Element | None) -> str:
    if elem is None:
        return ""
    node = elem.find(".//mattext")
    return (node.text or "") if node is not None else ""


def _metadata(item: Element) -> dict[str, str]:
    """Item metadata as {label: value}."""
    fields = {}
    for f in item.iter("qtimetadatafield"):
        label = f.findtext("fieldlabel")
        if label:
            fields[label] = (f.findtext("fieldentry") or "").strip()
    return fields


def _correct_idents(item: Element) -> set[str]:
    """Response idents marked correct by the item's scoring rules.

    A correct condition sets SCORE to 100. For multiple-answer questions the
    condition is an <and> of required choices plus <not> wrappers for the
    wrong ones; only the direct (un-negated) matches count as correct.
    """
    correct: set[str] = set()
    for cond in item.iter("respcondition"):
        setvar = cond.find("setvar")
        scores_full = setvar is not None and (setvar.text or "").strip() in {"100", "100.0"}
        if not scores_full:
            continue
        conditionvar = cond.find("conditionvar")
        if conditionvar is None:
            continue
        container = conditionvar.find("and")
        if container is None:
            container = conditionvar
        for eq in container.findall("varequal"):
            if eq.text:
                correct.add(eq.text.strip())
    return correct


def _choice_options(item: Element) -> list[ParsedOption]:
    correct = _correct_idents(item)
    options = []
    for label in item.iter("response_label"):
        ident = label.get("ident", "")
        text = html_to_text(_mattext(label)) or _mattext(label).strip()
        options.append(ParsedOption(text=text, is_correct=ident in correct))
    return options


def _accepted_answers(item: Element) -> list[ParsedOption]:
    """Fill-in-the-blank: every accepted answer text is a correct option."""
    return [ParsedOption(text=text, is_correct=True) for text in sorted(_correct_idents(item))]


def _find_image(html: str, archive: zipfile.ZipFile, names: list[str]) -> ParsedImage | None:
    img = BeautifulSoup(html, "html.parser").find("img") if html else None
    src = img.get("src", "") if img else ""
    if not src.startswith(IMAGE_PREFIX):
        return None
    wanted = urllib.parse.unquote(src[len(IMAGE_PREFIX):]).split("?", 1)[0]
    for name in names:
        if name.endswith(wanted):
            return ParsedImage(filename=PurePosixPath(name).name, data=archive.read(name))
    return None


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _parse_item(item: Element, archive: zipfile.ZipFile, names: list[str],
                warnings: list[str]) -> ParsedQuestion | None:
    meta = _metadata(item)
    source_type = meta.get("question_type", "")
    ident = item.get("ident", "")

    if source_type in NON_QUESTION_TYPES:
        return None

    html = _mattext(item.find("presentation/material"))
    try:
        points = float(meta.get("points_possible") or 1)
    except ValueError:
        points = 1.0

    code = QUESTION_TYPES.get(source_type, "OT")
    if code in {"MC", "TF", "MS"}:
        options = _choice_options(item)
        if not any(o.is_correct for o in options):
            warnings.append(f"Question {ident}: no correct answer found.")
    elif code == "FB":
        options = _accepted_answers(item)
    else:
        options = []
        if code == "OT":
            warnings.append(
                f"Question {ident}: type '{source_type or 'unknown'}' isn't fully supported; "
                "imported the text only."
            )

    return ParsedQuestion(
        ident=ident,
        source_type=source_type,
        question_type=code,
        text=html_to_text(html),
        text_html=html,
        points=points,
        options=options,
        image=_find_image(html, archive, names),
    )


def _read_meta(archive: zipfile.ZipFile, folder: str) -> tuple[str, str]:
    """(title, instructions) from a quiz folder's assessment_meta.xml, if present."""
    path = f"{folder}/assessment_meta.xml" if folder else "assessment_meta.xml"
    try:
        root = _parse_xml(archive.read(path))
    except KeyError:
        return "", ""
    return (root.findtext("title") or "").strip(), html_to_text(root.findtext("description") or "")


def parse_qti_zip(source: str | BinaryIO) -> ParseResult:
    """Parse a Canvas QTI export zip (path or file object)."""
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise QTIError("That file isn't a zip archive. Export the quiz from Canvas as QTI.") from exc

    result = ParseResult()
    with archive:
        names = archive.namelist()
        for name in sorted(n for n in names if n.lower().endswith(".xml")):
            if PurePosixPath(name).name in {"imsmanifest.xml", "assessment_meta.xml"}:
                continue
            root = _parse_xml(archive.read(name))
            if root.tag != "questestinterop":
                continue
            assessment = root.find("assessment")
            if assessment is None:
                continue

            folder = str(PurePosixPath(name).parent)
            folder = "" if folder == "." else folder
            meta_title, instructions = _read_meta(archive, folder)

            parsed = ParsedAssessment(
                ident=assessment.get("ident", ""),
                title=meta_title or assessment.get("title", "") or "Untitled test",
                instructions=instructions,
            )
            for item in assessment.iter("item"):
                question = _parse_item(item, archive, names, result.warnings)
                if question is not None:
                    parsed.questions.append(question)
            result.assessments.append(parsed)

    if not result.assessments:
        raise QTIError("No quizzes found in this file. Export the quiz from Canvas as QTI.")
    return result
