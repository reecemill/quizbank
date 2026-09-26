"""Build Canvas-style QTI export zips in memory for tests.

The XML mirrors what Canvas actually exports for Classic Quizzes: namespaced
<questestinterop>, metadata as label/entry pairs, HTML prompts escaped inside
<mattext>, and scoring rules as <respcondition> blocks.
"""

import io
import zipfile
from html import escape

NS = 'xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2"'

# A 1x1 transparent PNG.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4b8"
    "0000000049454e44ae426082"
)


def _meta(fields, reverse=False):
    pairs = list(fields.items())
    if reverse:
        pairs.reverse()
    rows = "".join(
        f"<qtimetadatafield><fieldlabel>{k}</fieldlabel><fieldentry>{v}</fieldentry></qtimetadatafield>"
        for k, v in pairs
    )
    return f"<itemmetadata><qtimetadata>{rows}</qtimetadata></itemmetadata>"


def _prompt(html):
    return f'<material><mattext texttype="text/html">{escape(html)}</mattext></material>'


def _choices(choices):
    labels = "".join(
        f'<response_label ident="{ident}"><material><mattext texttype="text/plain">{escape(text)}'
        f"</mattext></material></response_label>"
        for ident, text in choices
    )
    return f'<response_lid ident="response1"><render_choice>{labels}</render_choice></response_lid>'


def _full_score(conditionvar):
    return (
        '<respcondition continue="No">'
        f"<conditionvar>{conditionvar}</conditionvar>"
        '<setvar action="Set" varname="SCORE">100</setvar>'
        "</respcondition>"
    )


def _feedback_condition(ident):
    # Canvas adds these per-answer feedback rules; they must NOT count as correct.
    return (
        '<respcondition continue="Yes">'
        f'<conditionvar><varequal respident="response1">{ident}</varequal></conditionvar>'
        f'<displayfeedback feedbacktype="Response" linkrefid="{ident}_fb"/>'
        "</respcondition>"
    )


def multiple_choice_item(reverse_meta=False):
    return (
        '<item ident="q_mc" title="Question">'
        + _meta({"question_type": "multiple_choice_question", "points_possible": "2.0"}, reverse_meta)
        + "<presentation>"
        + _prompt('<p>What does <strong>CPU</strong> stand for?</p>'
                  '<p><img src="$IMS-CC-FILEBASE$/Quiz%20Files/cpu%20diagram.png" alt="cpu"></p>')
        + _choices([("a1", "Central Processing Unit"), ("a2", "Computer Power Unit"),
                    ("a3", "Central Program Utility")])
        + "</presentation><resprocessing>"
        + _feedback_condition("a2")
        + _full_score('<varequal respident="response1">a1</varequal>')
        + "</resprocessing></item>"
    )


def true_false_item():
    return (
        '<item ident="q_tf" title="Question">'
        + _meta({"question_type": "true_false_question", "points_possible": "1.0"})
        + "<presentation>"
        + _prompt("<p>A byte is 8 bits.</p>")
        + _choices([("t1", "True"), ("t2", "False")])
        + "</presentation><resprocessing>"
        + _full_score('<varequal respident="response1">t1</varequal>')
        + "</resprocessing></item>"
    )


def multiple_answers_item():
    return (
        '<item ident="q_ms" title="Question">'
        + _meta({"question_type": "multiple_answers_question", "points_possible": "3.0"})
        + "<presentation>"
        + _prompt("<p>Which of these are programming languages?</p>")
        + _choices([("m1", "Python"), ("m2", "HTML"), ("m3", "Rust")])
        + "</presentation><resprocessing>"
        + _full_score(
            '<and><varequal respident="response1">m1</varequal>'
            '<not><varequal respident="response1">m2</varequal></not>'
            '<varequal respident="response1">m3</varequal></and>'
        )
        + "</resprocessing></item>"
    )


def short_answer_item():
    return (
        '<item ident="q_fb" title="Question">'
        + _meta({"question_type": "short_answer_question", "points_possible": "1.0"})
        + "<presentation>"
        + _prompt("<p>The keyword to define a function in Python is ____.</p>")
        + '<response_str ident="response1" rcardinality="Single"><render_fib/></response_str>'
        + "</presentation><resprocessing>"
        + _full_score('<varequal respident="response1">def</varequal>'
                      '<varequal respident="response1">DEF</varequal>')
        + "</resprocessing></item>"
    )


def essay_item():
    return (
        '<item ident="q_es" title="Question">'
        + _meta({"question_type": "essay_question", "points_possible": "10.0"})
        + "<presentation>" + _prompt("<p>Explain recursion.</p>") + "</presentation></item>"
    )


def text_only_item():
    return (
        '<item ident="q_txt" title="Question">'
        + _meta({"question_type": "text_only_question", "points_possible": "0"})
        + "<presentation>" + _prompt("<p>Read the passage below.</p>") + "</presentation></item>"
    )


def matching_item():
    return (
        '<item ident="q_ma" title="Question">'
        + _meta({"question_type": "matching_question", "points_possible": "4.0"})
        + "<presentation>" + _prompt("<p>Match each term to its definition.</p>") + "</presentation></item>"
    )


def questions_xml(ident, title, items):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><questestinterop {NS}>'
        f'<assessment ident="{ident}" title="{escape(title)}"><section ident="root_section">'
        + "".join(items)
        + "</section></assessment></questestinterop>"
    )


def meta_xml(ident, title, description_html):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<quiz identifier="{ident}" xmlns="http://canvas.instructure.com/xsd/cccv1p0">'
        f"<title>{escape(title)}</title><description>{escape(description_html)}</description></quiz>"
    )


def build_export(quizzes=None, include_image=True) -> io.BytesIO:
    """A Canvas export zip. `quizzes` is a list of (ident, title, items)."""
    if quizzes is None:
        quizzes = [("quiz1", "Quiz 1: Computing Basics", [
            multiple_choice_item(), true_false_item(), multiple_answers_item(),
            short_answer_item(), essay_item(), text_only_item(), matching_item(),
        ])]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", "<manifest/>")
        for ident, title, items in quizzes:
            zf.writestr(f"{ident}/assessment_meta.xml",
                        meta_xml(ident, title, "<p>Answer <em>all</em> questions.</p>"))
            zf.writestr(f"{ident}/{ident}.xml", questions_xml(ident, title, items))
        if include_image:
            zf.writestr("web_resources/Quiz Files/cpu diagram.png", PNG_BYTES)
    buf.seek(0)
    return buf
