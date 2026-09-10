from django.contrib import admin

from .models import ExtractedData, Rule, Scan, ScanImage, StandardPackSize, Violation


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("code", "citation", "title", "severity", "kind", "verified", "active")
    list_filter = ("severity", "kind", "verified", "active")
    list_editable = ("verified", "active")
    search_fields = ("code", "citation", "title", "requirement")
    ordering = ("order", "code")


@admin.register(StandardPackSize)
class StandardPackSizeAdmin(admin.ModelAdmin):
    list_display = ("commodity", "unit", "sizes", "verified")
    list_editable = ("verified",)
    search_fields = ("commodity", "keywords")


class ScanImageInline(admin.TabularInline):
    model = ScanImage
    extra = 0


class ViolationInline(admin.TabularInline):
    model = Violation
    extra = 0
    readonly_fields = ("rule", "status", "severity", "observed", "message")
    can_delete = False


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("id", "product_label", "verdict", "status", "is_demo", "created_at")
    list_filter = ("verdict", "status", "is_demo")
    inlines = [ScanImageInline, ViolationInline]


admin.site.register(ExtractedData)
admin.site.site_header = "Label compliance - admin"
