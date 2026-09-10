from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from compliance import views

urlpatterns = [
    path("", views.app, name="app"),
    path("admin/", admin.site.urls),
    path("api/", include("compliance.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
