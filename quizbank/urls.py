from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path


class LoginView(auth_views.LoginView):
    """The sign-in page, showing the public demo's account when one is set."""

    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, demo_username=settings.QUIZBANK_DEMO_USERNAME,
                                         demo_password=settings.QUIZBANK_DEMO_PASSWORD)


urlpatterns = [
    path("", include("bank.urls")),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
