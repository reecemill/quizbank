from django.contrib import admin

from .models import AnswerOption, Assignment, Attempt, Course, Question, Response, Test, TestQuestion


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 0


class TestQuestionInline(admin.TabularInline):
    model = TestQuestion
    extra = 0
    autocomplete_fields = ["question"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["short_text", "question_type", "points", "course"]
    list_filter = ["question_type", "course"]
    search_fields = ["text"]
    inlines = [AnswerOptionInline]

    @admin.display(description="Question")
    def short_text(self, obj):
        return obj.text[:80]


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ["title", "course", "created_at"]
    list_filter = ["course"]
    inlines = [TestQuestionInline]


class ResponseInline(admin.TabularInline):
    model = Response
    extra = 0
    fields = ["order", "question", "text", "points"]
    readonly_fields = ["order", "question", "text"]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["test", "code", "is_open", "show_answers", "created_at"]
    list_filter = ["is_open"]


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ["student_name", "assignment", "score", "max_score", "submitted_at"]
    search_fields = ["student_name"]
    inlines = [ResponseInline]
