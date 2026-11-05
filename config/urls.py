from django.contrib import admin
from django.urls import path

from knowledge_base.views import retrieve

urlpatterns = [path("admin/", admin.site.urls), path("api/retrieve/", retrieve, name="retrieve")]
