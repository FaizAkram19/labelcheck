from rest_framework import serializers

from .models import Rule, Scan, ScanImage, Violation


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = ["code", "citation", "title", "requirement", "severity", "kind", "verified"]


class ViolationSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="rule.code")
    citation = serializers.CharField(source="rule.citation")
    title = serializers.CharField(source="rule.title")
    requirement = serializers.CharField(source="rule.requirement")
    verified = serializers.BooleanField(source="rule.verified")

    class Meta:
        model = Violation
        fields = ["code", "citation", "title", "requirement", "verified",
                  "status", "severity", "observed", "message"]


class ScanImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ScanImage
        fields = ["panel", "url"]

    def get_url(self, obj):
        try:
            return obj.image.url
        except ValueError:
            return ""


class ScanListSerializer(serializers.ModelSerializer):
    counts = serializers.ReadOnlyField()

    class Meta:
        model = Scan
        fields = ["id", "created_at", "product_label", "status", "verdict",
                  "is_demo", "counts"]


class ScanDetailSerializer(serializers.ModelSerializer):
    violations = ViolationSerializer(many=True, read_only=True)
    images = ScanImageSerializer(many=True, read_only=True)
    counts = serializers.ReadOnlyField()
    fields_read = serializers.SerializerMethodField()
    confidence = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()

    class Meta:
        model = Scan
        fields = ["id", "created_at", "product_label", "status", "verdict",
                  "is_imported", "exempt_reason", "error", "is_demo", "counts",
                  "fields_read", "confidence", "notes", "images", "violations"]

    def _raw(self, obj):
        extracted = getattr(obj, "extracted", None)
        return extracted.raw_response if extracted else {}

    def get_fields_read(self, obj):
        extracted = getattr(obj, "extracted", None)
        return extracted.merged_fields if extracted else {}

    def get_confidence(self, obj):
        return self._raw(obj).get("confidence", {})

    def get_notes(self, obj):
        return self._raw(obj).get("notes", "")
