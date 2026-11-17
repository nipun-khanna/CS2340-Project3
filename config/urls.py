from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from knowledge_base.views import ask, retrieve, developer_tools

urlpatterns = [
    path("", ask, name="ask"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("developer/", developer_tools, name="developer_tools"),
    path("admin/", admin.site.urls),
    path("api/retrieve/", retrieve, name="retrieve"),
]
