"""Create example checks that replay without any network call.

These exist so the demo survives a dead venue connection, and so the frontend
has something to show before the first real scan. Replace them with real scans
of real products as soon as the photographs arrive - a judge would rather see
a genuine local brand fail than a made-up one.
"""
from django.core.management.base import BaseCommand

from compliance.engine.runner import evaluate
from compliance.models import ExtractedData, Rule, Scan, StandardPackSize, Violation

FIELDS = ["product_name", "common_name", "manufacturer_name", "manufacturer_address",
          "importer_name", "country_of_origin", "net_quantity", "mrp",
          "manufacture_date", "expiry_date", "consumer_care", "veg_nonveg_mark",
          "batch_number"]


def rec(label, **kw):
    f = {k: "" for k in FIELDS}
    f.update(kw)
    return label, f


EXAMPLES = [
    rec("Marie biscuits, national brand",
        product_name="Krisp Marie Gold", common_name="Marie Biscuits",
        manufacturer_name="Krisp Foods Pvt Ltd",
        manufacturer_address="Plot 14, MIDC Bhosari, Pune 411026, Maharashtra",
        net_quantity="Net Wt. 200 g", mrp="MRP Rs. 30.00 (inclusive of all taxes)",
        manufacture_date="Mfd: 06/2026", consumer_care="care@krispfoods.in | 1800 123 4567",
        veg_nonveg_mark="veg", batch_number="B2261"),

    rec("Namkeen, local brand",
        product_name="Sharma Bhujia", common_name="Namkeen Bhujia",
        manufacturer_name="Sharma Snacks",
        manufacturer_address="Burrabazar, Kolkata",
        net_quantity="Net Wt. 180gm", mrp="Rs. 40/-",
        manufacture_date="", consumer_care="", veg_nonveg_mark="veg"),

    rec("Refined sunflower oil, wrong unit",
        product_name="Suraj Refined Sunflower Oil", common_name="Refined Sunflower Oil",
        manufacturer_name="Suraj Oils Ltd",
        manufacturer_address="Survey 88, Rajkot 360003, Gujarat",
        net_quantity="Net Volume: 1500 ml", mrp="MRP Rs. 210 incl. of all taxes",
        manufacture_date="May 2026", consumer_care="grievance@surajoils.com",
        veg_nonveg_mark="veg"),

    rec("Imported chocolate, no country of origin",
        product_name="Alpine Dark 70%", common_name="Dark Chocolate Bar",
        manufacturer_name="Alpine Confiserie GmbH",
        manufacturer_address="Zurichstrasse 40, Bern",
        importer_name="Global Gourmet Imports Pvt Ltd, Mumbai 400001",
        net_quantity="100 g", mrp="MRP Rs. 450 (inclusive of all taxes)",
        manufacture_date="03/2026", consumer_care="hello@globalgourmet.in",
        veg_nonveg_mark="veg"),

    rec("Toilet soap, non-standard pack size",
        product_name="Neem Fresh Bathing Bar", common_name="Toilet Soap",
        manufacturer_name="Vanya Personal Care Pvt Ltd",
        manufacturer_address="Industrial Estate, Hosur 635126, Tamil Nadu",
        net_quantity="Net Wt. 90 g", mrp="MRP Rs. 48 inclusive of all taxes",
        manufacture_date="Apr 2026", consumer_care="1800 200 3030, care@vanya.co.in"),

    rec("Atta, qualifying word on quantity",
        product_name="Ghar Ka Chakki Atta", common_name="Whole Wheat Atta",
        manufacturer_name="Annapurna Flour Mills",
        manufacturer_address="GT Road, Ludhiana 141003, Punjab",
        net_quantity="Net Wt. approx 5 kg", mrp="MRP Rs. 250 (incl. of all taxes)",
        manufacture_date="07/2026", consumer_care="info@annapurnamills.in",
        veg_nonveg_mark="veg"),

    rec("Shampoo sachet, below the threshold",
        product_name="SilkGlow Shampoo Sachet", common_name="Hair Shampoo",
        manufacturer_name="SilkGlow India Ltd",
        manufacturer_address="Baddi 173205, Himachal Pradesh",
        net_quantity="8 ml", mrp="", manufacture_date="02/2026",
        consumer_care="care@silkglow.in"),

    rec("Detergent, several defects at once",
        product_name="ShineMax Washing Powder", common_name="Detergent Powder",
        manufacturer_name="ShineMax Industries", manufacturer_address="Howrah",
        net_quantity="Net Wt. 1200 gm", mrp="Rs 95", manufacture_date="",
        consumer_care="Customer Care Department"),
]


class Command(BaseCommand):
    help = "Create offline example checks for the demo and for the empty state."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing demo scans first.")

    def handle(self, *args, **options):
        if options["reset"]:
            n = Scan.objects.filter(is_demo=True).count()
            Scan.objects.filter(is_demo=True).delete()
            self.stdout.write(f"Removed {n} existing example checks.")

        rules = list(Rule.objects.filter(active=True))
        packs = list(StandardPackSize.objects.all())
        if not rules:
            self.stderr.write("No rules loaded. Run: python manage.py seed_rules")
            return

        made = 0
        for label, fields in EXAMPLES:
            if Scan.objects.filter(product_label=label, is_demo=True).exists():
                continue
            imported = bool(fields["country_of_origin"] or fields["importer_name"])
            verdict, reason, results = evaluate(fields, rules, packs, is_imported=imported)
            scan = Scan.objects.create(
                product_label=label, status="DONE", verdict=verdict,
                exempt_reason=reason[:200], is_imported=imported, is_demo=True,
            )
            ExtractedData.objects.create(
                scan=scan,
                raw_response={"fields": fields, "confidence": {}, "notes": "",
                              "_source": "seeded example, not a real extraction"},
                merged_fields=fields, model_name="seeded",
            )
            Violation.objects.bulk_create([
                Violation(scan=scan, rule=r["rule"], status=r["status"],
                          severity=r["severity"], observed=r["observed"][:300],
                          message=r["message"])
                for r in results
            ])
            made += 1
            self.stdout.write(f"  {verdict:<14} {label}")

        self.stdout.write(self.style.SUCCESS(f"{made} example checks created."))
