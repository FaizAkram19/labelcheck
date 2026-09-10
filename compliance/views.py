from django.conf import settings
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .engine.runner import evaluate
from .extraction import gemini
from .models import ExtractedData, Rule, Scan, ScanImage, StandardPackSize, Violation
from .serializers import RuleSerializer, ScanDetailSerializer, ScanListSerializer

TRUE = {"1", "true", "yes", "on"}


def _run_rules(scan, merged, is_imported, manual_flags):
    rules = list(Rule.objects.filter(active=True))
    pack_sizes = list(StandardPackSize.objects.all())
    verdict, exempt_reason, results = evaluate(
        merged, rules, pack_sizes, is_imported=is_imported, manual_flags=manual_flags
    )
    Violation.objects.filter(scan=scan).delete()
    Violation.objects.bulk_create([
        Violation(scan=scan, rule=r["rule"], status=r["status"], severity=r["severity"],
                  observed=r["observed"][:300], message=r["message"])
        for r in results
    ])
    scan.verdict = verdict
    scan.exempt_reason = exempt_reason[:200]
    scan.is_imported = is_imported
    scan.status = "DONE"
    scan.save()
    return scan


@api_view(["POST"])
def create_scan(request):
    """Accept one or two label images and return the compliance report.

    Runs synchronously. A scan takes a few seconds, and a background worker
    would be one more moving part to explain and to fail on demo day.
    """
    images = request.FILES.getlist("images") or request.FILES.getlist("image")
    if not images:
        return Response({"detail": "Attach at least one image as 'images'."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(images) > 3:
        return Response({"detail": "At most three images per scan."},
                        status=status.HTTP_400_BAD_REQUEST)

    manual_flags = {
        "restaurant_packed": request.data.get("restaurant_packed", "") in TRUE,
        "drug_price_control": request.data.get("drug_price_control", "") in TRUE,
        "institutional": request.data.get("institutional", "") in TRUE,
    }

    scan = Scan.objects.create(
        status="EXTRACTING",
        product_label=(request.data.get("product_label") or "")[:160],
    )

    blobs = []
    panels = request.data.getlist("panels") if hasattr(request.data, "getlist") else []
    for i, f in enumerate(images):
        panel = panels[i] if i < len(panels) and panels[i] in ("DECLARATION", "FRONT") else (
            "DECLARATION" if i == 0 else "FRONT")
        ScanImage.objects.create(scan=scan, image=f, panel=panel)
        f.seek(0)
        blobs.append((f.name, f.read()))

    try:
        raw = gemini.extract(blobs, model=settings.GEMINI_MODEL,
                             api_key=settings.GEMINI_API_KEY)
    except gemini.ExtractionError as exc:
        scan.status = "FAILED"
        scan.error = str(exc)
        scan.save()
        return Response(
            {"detail": str(exc), "scan_id": scan.id,
             "hint": "Previously scanned products are available from the history and need no "
                     "network call."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    merged = gemini.merge_fields(raw)
    ExtractedData.objects.update_or_create(
        scan=scan,
        defaults=dict(raw_response=raw, merged_fields=merged,
                      model_name=raw.get("_model", "")),
    )
    if not scan.product_label:
        scan.product_label = (merged.get("product_name")
                              or merged.get("common_name") or "")[:160]

    _run_rules(scan, merged, gemini.looks_imported(merged), manual_flags)
    return Response(ScanDetailSerializer(scan).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def scan_detail(request, pk):
    try:
        scan = Scan.objects.prefetch_related("violations__rule", "images").get(pk=pk)
    except Scan.DoesNotExist:
        return Response({"detail": "No such scan."}, status=status.HTTP_404_NOT_FOUND)
    return Response(ScanDetailSerializer(scan).data)


@api_view(["GET"])
def scan_list(request):
    qs = Scan.objects.exclude(status="FAILED")
    if request.GET.get("demo") in TRUE:
        qs = qs.filter(is_demo=True)
    return Response(ScanListSerializer(qs[:60], many=True).data)


@api_view(["POST"])
def recheck(request, pk):
    """Re-run the rules against stored extraction. No network call.

    Useful after the research pair corrects a rule: every past scan can be
    re-evaluated against the amended catalogue without rescanning anything.
    """
    try:
        scan = Scan.objects.get(pk=pk)
        extracted = scan.extracted
    except (Scan.DoesNotExist, ExtractedData.DoesNotExist):
        return Response({"detail": "No stored extraction for that scan."},
                        status=status.HTTP_404_NOT_FOUND)
    _run_rules(scan, extracted.merged_fields, scan.is_imported, {})
    return Response(ScanDetailSerializer(scan).data)


@api_view(["GET"])
def rules(request):
    return Response(RuleSerializer(Rule.objects.filter(active=True), many=True).data)


@api_view(["GET"])
def health(request):
    return Response({
        "ok": True,
        "rules_loaded": Rule.objects.filter(active=True).count(),
        "rules_verified": Rule.objects.filter(active=True, verified=True).count(),
        "pack_sizes_loaded": StandardPackSize.objects.count(),
        "extraction_key_present": bool(settings.GEMINI_API_KEY),
        "scans": Scan.objects.count(),
    })


def app(request):
    return render(request, "app.html")
