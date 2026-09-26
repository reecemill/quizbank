from django.contrib import admin

from .models import AnswerOption, Course, Question, Test, TestQuestion


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
