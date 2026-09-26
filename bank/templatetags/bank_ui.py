"""Template helpers for the question bank pages."""

from decimal import Decimal

import nh3
from django import template
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe

register = template.Library()

# Formatting that Canvas prompts use. Images are dropped: the importer already
# saved each question's image, and the pages show it on its own.
PROMPT_TAGS = {
    "p", "br", "hr", "div", "span", "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "code", "pre", "blockquote", "ul", "ol", "li", "a",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td",
}
PROMPT_ATTRIBUTES = {"a": {"href", "title"}, "th": {"colspan", "rowspan"}, "td": {"colspan", "rowspan"}}

# Courses cycle through this many colors (--course-0 and up, in app.css).
COURSE_COLORS = 8

TYPE_SHORT = {"MC": "MC", "TF": "T/F", "MS": "Multi", "FB": "Fill in", "ES": "Essay", "OT": "Other"}


@register.filter
def question_html(question):
    """The prompt, safe to show: the imported Canvas HTML with anything risky
    (scripts, styles, event handlers, javascript: links) removed. Falls back to
    the plain-text copy."""
    if question.text_html:
        return mark_safe(nh3.clean(question.text_html, tags=PROMPT_TAGS, attributes=PROMPT_ATTRIBUTES))
    return mark_safe(linebreaks(question.text, autoescape=True))


@register.filter
def course_color(course):
    """The CSS color for a course, like the colors Canvas gives courses."""
    return f"var(--course-{(course.pk - 1) % COURSE_COLORS})"


@register.filter
def type_short(code):
    """A question type's badge label, e.g. 'T/F'."""
    return TYPE_SHORT.get(code, code)


@register.filter
def num(value):
    """A number without trailing zeros: 2.00 -> '2', 1.50 -> '1.5'."""
    return format(Decimal(value or 0).normalize(), "f")


@register.filter
def points(value):
    """'1 pt', '2 pts', '1.5 pts'."""
    text = num(value)
    return f"{text} pt" if Decimal(value or 0) == 1 else f"{text} pts"


@register.filter
def grade_band(percent):
    """A color band for a score: 'a' (90%+), 'b' (70%+), 'c' (50%+), or 'd'."""
    percent = percent or 0
    return "a" if percent >= 90 else "b" if percent >= 70 else "c" if percent >= 50 else "d"


@register.filter
def initials(person):
    """Up to two letters for an avatar, from a user or a typed name."""
    name = person if isinstance(person, str) else (person.get_full_name() or person.get_username())
    return "".join(part[0] for part in name.split()[:2]).upper()
