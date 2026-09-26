from django.urls import path

from . import student_views, views

app_name = "bank"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("questions/", views.QuestionListView.as_view(), name="questions"),
    path("questions/<int:pk>/", views.QuestionDetailView.as_view(), name="question"),
    path("courses/<int:pk>/", views.QuestionListView.as_view(), name="course"),
    path("courses/<int:pk>/quizzes/", views.QuizListView.as_view(), name="course_quizzes"),
    path("quizzes/<int:pk>/", views.QuizDetailView.as_view(), name="quiz"),
    path("quizzes/<int:pk>/give/", views.GiveQuizView.as_view(), name="give"),
    path("import/", views.ImportView.as_view(), name="import"),

    # A quiz given to students: its results, settings, and each student's attempt.
    path("given/<str:code>/", views.ResultsView.as_view(), name="results"),
    path("given/<str:code>/settings/", views.AssignmentSettingsView.as_view(), name="assignment_settings"),
    path("given/<str:code>/results.csv", views.ResultsCSVView.as_view(), name="results_csv"),
    path("given/<str:code>/<int:attempt_pk>/", views.AttemptView.as_view(), name="attempt"),

    # Student pages: no sign-in needed.
    path("take/<str:code>/", student_views.TakeQuizView.as_view(), name="take"),
    path("take/<str:code>/done/", student_views.TakeDoneView.as_view(), name="take_done"),
]
