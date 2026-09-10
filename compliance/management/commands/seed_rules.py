"""Load the rule catalogue and the Second Schedule extract.

Idempotent - safe to run repeatedly. Every row starts with verified=False;
tick them in the admin as the research pair returns the sign-off sheet.
"""
from django.core.management.base import BaseCommand
from compliance.models import Rule, StandardPackSize

RULES = [
    ("R01", "Rule 6(1)(a)", "Manufacturer, packer or importer name and address",
     "Name and address of the manufacturer. Where the manufacturer is not the packer, both. "
     "For an imported package, the name and address of the importer.",
     "MAJOR", "PRESENCE", "manufacturer_name", 10),
    ("R02", "Rule 6(1)(aa)", "Country of origin (imported products)",
     "For imported products, the country of origin or of manufacture or of assembly. "
     "Inserted by G.S.R. 629(E) dated 23.06.2017.",
     "MAJOR", "PRESENCE", "country_of_origin", 20),
    ("R03", "Rule 6(1)(b)", "Common or generic name of the commodity",
     "The common or generic name of the commodity contained in the package.",
     "MAJOR", "PRESENCE", "common_name", 30),
    ("R04", "Rule 6(1)(c)", "Net quantity",
     "The net quantity in terms of the standard unit of weight or measure, or the number of "
     "items where sold by number.",
     "MAJOR", "PRESENCE", "net_quantity", 40),
    ("R05", "Rule 6(1)(d)", "Month and year of manufacture, packing or import",
     "The month and year in which the commodity was manufactured, pre-packed or imported. "
     "May be expressed in words, numerals, or both.",
     "MAJOR", "PRESENCE", "manufacture_date", 50),
    ("R06", "Rule 6(1)(e)", "Retail sale price",
     "The retail sale price of the package.",
     "MAJOR", "PRESENCE", "mrp", 60),
    ("R07", "Rule 6(2)", "Consumer care details",
     "Name, address, telephone number and e-mail address (where available) of the person or "
     "office to be contacted in case of consumer complaints.",
     "MAJOR", "PRESENCE", "consumer_care", 70),
    ("R08", "Rule 2(m)", "Retail sale price stated in the required form",
     "The price must read 'Maximum or Max. retail price Rs ... inclusive of all taxes' or "
     "'MRP Rs ... incl. of all taxes'.",
     "MINOR", "FORMAT", "mrp", 80),
    ("R09", "Rule 13(2) and 13(3)", "Correct unit for the magnitude declared",
     "Below one kilogram the unit is the gram; below one litre, the millilitre. At or above one "
     "kilogram or one litre, the kilogram or litre.",
     "MINOR", "FORMAT", "net_quantity", 90),
    ("R10", "Rule 13(5)", "International System units only",
     "Only International System units may be used for net quantity. For items sold by number "
     "the symbol shall be N or U.",
     "MINOR", "FORMAT", "net_quantity", 100),
    ("R11", "Rule 13(4)", "No dozen, score or gross",
     "No number called the dozen, score, gross or great gross shall be specified or indicated "
     "on any package.",
     "MINOR", "FORMAT", "net_quantity", 110),
    ("R12", "Rule 12(6)", "No qualifying words on the quantity declaration",
     "The quantity declaration must not contain words creating an exaggerated, misleading or "
     "inadequate impression - for example minimum, not less than, average, about, approximately.",
     "MINOR", "FORMAT", "net_quantity", 120),
    ("R13", "Rule 5 and Second Schedule", "Standard pack size for scheduled commodities",
     "Commodities listed in the Second Schedule must be packed in the standard quantities "
     "specified there.",
     "MINOR", "FORMAT", "net_quantity", 130),
    ("R14", "Food safety labelling regulations", "Vegetarian / non-vegetarian mark",
     "The green or brown symbol is detected and displayed for information. It is governed by "
     "food safety law, not the Legal Metrology rules, so no compliance claim is made.",
     "INFO", "INFO", "veg_nonveg_mark", 140),
]

# commodity, keywords, unit, sizes, unrestricted_below, multiples_above, multiple_step
PACK_SIZES = [
    ("Biscuits", "biscuit,biscuits,cookie,cookies,cream biscuit", "g",
     "25,50,75,100,150,200,250,300,400,500,600,700,800,900,1000", None, 300, 100),
    ("Tea", "tea,tea leaves,tea powder,dust tea,green tea", "g",
     "25,50,100,125,250,500,1000", None, 1000, 1000),
    ("Coffee", "coffee,instant coffee,coffee powder", "g",
     "25,50,100,200,250,500,1000", None, 1000, 1000),
    ("Salt", "salt,iodised salt,iodized salt,table salt", "g",
     "50,100,200,500,750,1000,2000,5000", 50, 5000, 5000),
    ("Cereals and pulses", "dal,pulses,cereal,rajma,chana,moong,toor,arhar,urad,masoor", "g",
     "100,200,500,1000,2000,5000", None, 5000, 5000),
    ("Rice powder, flour, atta, rawa, suji", "atta,flour,maida,rawa,suji,sooji,besan", "g",
     "100,200,500,1000,2000,5000", None, 5000, 5000),
    ("Baby food and weaning food", "baby food,infant food,weaning food,cerelac", "g",
     "100,200,300,400,500,600,700,800,900,1000,2000,5000,10000", None, None, None),
    ("Milk powder", "milk powder,dairy whitener,skimmed milk powder", "g",
     "50,100,200,500,1000", 50, 1000, 500),
    ("Edible oil, vanaspati, ghee", "edible oil,mustard oil,sunflower oil,groundnut oil,"
     "refined oil,vanaspati,ghee,coconut oil", "ml",
     "50,100,200,500,1000,2000,3000,5000", None, 5000, 5000),
    ("Toilet soap", "toilet soap,bath soap,bathing bar,beauty soap", "g",
     "25,50,75,100,125,150,200,250,300", None, 150, 50),
    ("Laundry soap", "laundry soap,washing soap,detergent bar,detergent cake", "g",
     "50,75,100,150,200,250", None, 100, 50),
    ("Non-soapy detergent powder", "detergent powder,washing powder,detergent", "g",
     "50,100,200,500,700,1000,1500,2000", 50, 2000, 1000),
    ("Butter and margarine", "butter,margarine", "g",
     "25,50,100,200,500,1000,2000,5000", None, 5000, 5000),
    ("Bread", "bread,brown bread", "g", "100,200,300,400,500,600,700,800", None, 100, 100),
    ("Mineral and drinking water", "mineral water,drinking water,packaged water", "ml",
     "100,150,200,250,300,500,750,1000,1500,2000,3000,4000,5000", None, None, None),
    ("Aerated soft drinks and non-alcoholic beverages",
     "soft drink,aerated,cola,soda,beverage,juice,fruit drink", "ml",
     "65,100,125,150,200,250,300,330,500,750,1000,1500,2000,3000,4000,5000", None, None, None),
]


class Command(BaseCommand):
    help = "Seed the rule catalogue and the Second Schedule pack sizes."

    def handle(self, *args, **options):
        created = updated = 0
        for code, citation, title, requirement, severity, kind, field, order in RULES:
            obj, made = Rule.objects.update_or_create(
                code=code,
                defaults=dict(citation=citation, title=title, requirement=requirement,
                              severity=severity, kind=kind, field=field, order=order,
                              active=True),
            )
            created += made
            updated += (not made)
        self.stdout.write(self.style.SUCCESS(f"Rules: {created} created, {updated} updated."))

        c = u = 0
        for (commodity, keywords, unit, sizes, unrestricted_below,
             multiples_above, multiple_step) in PACK_SIZES:
            obj, made = StandardPackSize.objects.update_or_create(
                commodity=commodity,
                defaults=dict(keywords=keywords, unit=unit, sizes=sizes,
                              unrestricted_below=unrestricted_below,
                              multiples_above=multiples_above, multiple_step=multiple_step),
            )
            c += made
            u += (not made)
        self.stdout.write(self.style.SUCCESS(f"Pack sizes: {c} created, {u} updated."))
        self.stdout.write(
            "All rows are marked unverified. Tick `verified` in the admin as the research "
            "sign-off sheet comes back."
        )
