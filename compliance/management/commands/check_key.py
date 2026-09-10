"""First-run check: does the key work, and which model should we use?

Run this before anything else:

    python manage.py check_key

It lists the models your key can reach, then sends one generated test label
through the configured model and prints what came back.
"""
import io

from django.conf import settings
from django.core.management.base import BaseCommand

from compliance.extraction import gemini

LINES = [
    "SUNRISE FOODS PVT LTD",
    "Plot 22, Industrial Area",
    "Kolkata 700088, West Bengal",
    "",
    "SALTED BISCUITS",
    "Net Wt. 250gm",
    "MRP Rs. 45.00",
    "Mfd: 05/2026",
    "Care: help@sunrisefoods.in",
]


def make_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (700, 460), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for line in LINES:
        d.text((40, y), line, fill="black")
        y += 42
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Check the extraction key, list usable models, and run one test label."

    def add_arguments(self, parser):
        parser.add_argument("--models-only", action="store_true",
                            help="Just list the models, do not send a test label.")

    def handle(self, *args, **options):
        key = settings.GEMINI_API_KEY
        if not key:
            self.stderr.write(self.style.ERROR(
                "GEMINI_API_KEY is empty.\n"
                "  1. copy .env.example .env\n"
                "  2. paste your key into .env\n"
                "  3. run this again"))
            return

        kind = "authorization key" if key.startswith("AQ.") else (
            "standard key" if key.startswith("AIza") else "unrecognised format")
        self.stdout.write(f"Key type:  {kind}")
        self.stdout.write(f"Model set: {settings.GEMINI_MODEL}\n")

        # --- which models can this key reach -------------------------------
        self.stdout.write("Asking the API which models this key can use...")
        try:
            models = gemini.list_models(key)
        except gemini.ExtractionError as exc:
            self.stderr.write(self.style.ERROR(f"Failed: {exc}"))
            self.stderr.write(
                "\nIf this says the credentials are invalid, the key text itself is wrong - "
                "regenerate it at aistudio.google.com/apikey and paste the whole thing.")
            return

        flash = [m for m in models if "flash" in m and "lite" not in m]
        self.stdout.write(self.style.SUCCESS(f"  {len(models)} models available."))
        if flash:
            self.stdout.write("  Flash models (fast, free tier, good enough for label text):")
            for m in flash[:12]:
                marker = "  <- currently set" if m == settings.GEMINI_MODEL else ""
                self.stdout.write(f"    {m}{marker}")

        if settings.GEMINI_MODEL not in models:
            self.stderr.write(self.style.WARNING(
                f"\n'{settings.GEMINI_MODEL}' is not in that list. Pick one above and set it in "
                f".env:\n    GEMINI_MODEL={flash[0] if flash else models[0]}"))
            return

        if options["models_only"]:
            return

        # --- send one test label -------------------------------------------
        self.stdout.write("\nSending one generated test label...")
        try:
            raw = gemini.extract([("test.jpg", make_image())],
                                 model=settings.GEMINI_MODEL, api_key=key)
        except gemini.ExtractionError as exc:
            self.stderr.write(self.style.ERROR(f"Failed: {exc}"))
            return

        merged = gemini.merge_fields(raw)
        for k, v in merged.items():
            if v:
                self.stdout.write(f"  {k:<22} {v}")

        self.stdout.write("")
        if merged.get("net_quantity"):
            self.stdout.write(self.style.SUCCESS("Key works and the model returned fields."))
            if "gm" in merged["net_quantity"].replace(" ", "").replace(".", ""):
                self.stdout.write(
                    "It kept 'gm' rather than tidying it to 'g' - that is exactly what the "
                    "format checks need, so the prompt is behaving.")
            else:
                self.stdout.write(self.style.WARNING(
                    "It returned the quantity without the original 'gm' spelling. The model is "
                    "normalising the text, which would hide real violations. Tell me if you see "
                    "this - the prompt needs tightening."))
        else:
            self.stdout.write(self.style.WARNING(
                "The call worked but no net quantity came back. The generated test image is "
                "crude - try a real label photo through the app before worrying."))
