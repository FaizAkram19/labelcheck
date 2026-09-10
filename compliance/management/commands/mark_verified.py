"""Record that a human has checked the rule citations against the Gazette text.

Until this is run, every finding in the report carries a warning that its
citation is unverified. That warning is deliberate: an unchecked rule number in
front of a Legal Metrology audience is worse than no rule number.

Run it only once the research sign-off sheet is actually back:

    python manage.py mark_verified --by "Name" --all

Or tick individual rules as they are confirmed:

    python manage.py mark_verified --by "Name" R01 R02 R03
"""
from django.core.management.base import BaseCommand, CommandError

from compliance.models import Rule, StandardPackSize


class Command(BaseCommand):
    help = "Mark rule citations as verified against the official Rules text."

    def add_arguments(self, parser):
        parser.add_argument("codes", nargs="*", help="Rule codes, e.g. R01 R02.")
        parser.add_argument("--all", action="store_true", help="Mark every active rule.")
        parser.add_argument("--by", default="", help="Who checked them. Recorded in the output.")
        parser.add_argument("--pack-sizes", action="store_true",
                            help="Also mark the Second Schedule pack sizes.")
        parser.add_argument("--undo", action="store_true", help="Mark as unverified again.")

    def handle(self, *args, **options):
        codes, mark_all = options["codes"], options["all"]
        if not codes and not mark_all:
            raise CommandError("Give rule codes, or --all. Nothing was changed.")

        value = not options["undo"]
        qs = Rule.objects.filter(active=True)
        if not mark_all:
            qs = qs.filter(code__in=[c.upper() for c in codes])
            missing = set(c.upper() for c in codes) - set(qs.values_list("code", flat=True))
            if missing:
                raise CommandError(f"No such rule code: {', '.join(sorted(missing))}")

        n = qs.update(verified=value)
        word = "verified" if value else "unverified"
        self.stdout.write(self.style.SUCCESS(f"{n} rules marked {word}."))

        if options["pack_sizes"] or mark_all:
            m = StandardPackSize.objects.update(verified=value)
            self.stdout.write(self.style.SUCCESS(f"{m} pack-size rows marked {word}."))

        if options["by"] and value:
            self.stdout.write(f"Checked by: {options['by']}")

        remaining = Rule.objects.filter(active=True, verified=False).count()
        if remaining:
            self.stdout.write(self.style.WARNING(
                f"{remaining} active rules are still unverified and will show a warning in "
                "reports."))
        else:
            self.stdout.write("Every active rule is verified. Reports will no longer warn.")