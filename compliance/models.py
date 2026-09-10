from django.db import models


class Rule(models.Model):
    """One Legal Metrology requirement the engine can check.

    Rules live in the database, not in code, so an amendment is a data edit.
    The `code` maps to a check function in engine/checks.py.
    """

    SEVERITY = [
        ("MAJOR", "Major - legal violation"),
        ("MINOR", "Minor - formatting defect"),
        ("INFO", "Informational - not a Legal Metrology rule"),
    ]
    KIND = [
        ("PRESENCE", "Mandatory declaration must be present"),
        ("FORMAT", "Declaration present but must be written correctly"),
        ("INFO", "Detected and displayed, no compliance claim"),
    ]

    code = models.CharField(max_length=8, unique=True)
    citation = models.CharField(max_length=64)
    title = models.CharField(max_length=160)
    requirement = models.TextField()
    severity = models.CharField(max_length=8, choices=SEVERITY)
    kind = models.CharField(max_length=10, choices=KIND)
    field = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)
    verified = models.BooleanField(
        default=False,
        help_text="Ticked once a team member has confirmed this citation against the Gazette text.",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "code"]

    def __str__(self):
        return f"{self.code} {self.citation} - {self.title}"


class StandardPackSize(models.Model):
    """Second Schedule entries for Rule 5 (check R13)."""

    commodity = models.CharField(max_length=120)
    keywords = models.CharField(
        max_length=240,
        help_text="Comma-separated words matched against the extracted common name.",
    )
    unit = models.CharField(max_length=4, default="g")
    sizes = models.TextField(help_text="Comma-separated allowed sizes in the base unit.")
    multiples_above = models.FloatField(
        null=True, blank=True,
        help_text="Above this value any multiple of `multiple_step` is allowed.",
    )
    multiple_step = models.FloatField(null=True, blank=True)
    unrestricted_below = models.FloatField(null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["commodity"]

    def __str__(self):
        return self.commodity

    def allowed(self):
        return [float(s) for s in self.sizes.split(",") if s.strip()]

    def keyword_list(self):
        return [k.strip().lower() for k in self.keywords.split(",") if k.strip()]


class Scan(models.Model):
    STATUS = [
        ("PENDING", "Pending"),
        ("EXTRACTING", "Extracting"),
        ("DONE", "Done"),
        ("FAILED", "Failed"),
    ]
    VERDICT = [
        ("COMPLIANT", "Compliant"),
        ("NON_COMPLIANT", "Non-compliant"),
        ("EXEMPT", "Out of scope"),
        ("UNKNOWN", "Unknown"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS, default="PENDING")
    verdict = models.CharField(max_length=16, choices=VERDICT, default="UNKNOWN")
    product_label = models.CharField(max_length=160, blank=True)
    is_imported = models.BooleanField(default=False)
    exempt_reason = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)
    is_demo = models.BooleanField(
        default=False,
        help_text="Seeded example that replays without a network call.",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Scan #{self.pk} {self.product_label or '(unnamed)'} - {self.verdict}"

    @property
    def counts(self):
        v = list(self.violations.all())
        return {
            "major": sum(1 for x in v if x.severity == "MAJOR" and x.status == "FAIL"),
            "minor": sum(1 for x in v if x.severity == "MINOR" and x.status == "FAIL"),
            "passed": sum(1 for x in v if x.status == "PASS"),
        }


class ScanImage(models.Model):
    PANEL = [("DECLARATION", "Declaration panel"), ("FRONT", "Front panel")]

    scan = models.ForeignKey(Scan, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="scans/%Y/%m/")
    panel = models.CharField(max_length=12, choices=PANEL, default="DECLARATION")

    def __str__(self):
        return f"{self.get_panel_display()} for scan #{self.scan_id}"


class ExtractedData(models.Model):
    """Raw model output, kept verbatim.

    This is the audit trail. It is what lets anyone check whether a verdict came
    from a misreading, and it is why we can say the AI never decides compliance.
    """

    scan = models.OneToOneField(Scan, related_name="extracted", on_delete=models.CASCADE)
    raw_response = models.JSONField(default=dict)
    merged_fields = models.JSONField(default=dict)
    model_name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Extraction for scan #{self.scan_id}"


class Violation(models.Model):
    """One rule's result against one scan. Stored for passes too, so the report is complete."""

    STATUS = [("PASS", "Pass"), ("FAIL", "Fail"), ("SKIP", "Not applicable"), ("INFO", "Info")]

    scan = models.ForeignKey(Scan, related_name="violations", on_delete=models.CASCADE)
    rule = models.ForeignKey(Rule, on_delete=models.PROTECT)
    status = models.CharField(max_length=6, choices=STATUS)
    severity = models.CharField(max_length=8)
    observed = models.CharField(max_length=300, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["rule__order", "rule__code"]

    def __str__(self):
        return f"{self.rule.code} {self.status} on scan #{self.scan_id}"
