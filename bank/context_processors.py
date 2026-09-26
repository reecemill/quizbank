from django.db.models import Count

from .models import Course


def navigation(request):
    """Courses for the tab bar's Courses menu and the ⌘K palette. The queryset
    is lazy, so pages that don't show them (like the admin) never run the query."""
    if not request.user.is_authenticated:
        return {}
    return {"nav_courses": Course.objects.annotate(num_questions=Count("questions"))}
