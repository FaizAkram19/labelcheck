from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("rules/", views.rules, name="rules"),
    path("scans/", views.scan_list, name="scan-list"),
    path("scans/create/", views.create_scan, name="scan-create"),
    path("scans/<int:pk>/", views.scan_detail, name="scan-detail"),
    path("scans/<int:pk>/recheck/", views.recheck, name="scan-recheck"),
]
