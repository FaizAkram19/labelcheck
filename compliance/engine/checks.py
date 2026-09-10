"""The compliance checks.

One function per rule code. Each takes the merged extracted fields plus a small
context object and returns (status, observed, message).

Nothing here calls a model. The vision model's only job was to read the label
into fields; every pass or fail below is decided by explicit code, which is why
the same label always produces the same verdict.
"""
from . import normalize as nz

REGISTRY = {}


def check(code):
    def wrap(fn):
        REGISTRY[code] = fn
        return fn
    return wrap


PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"


def _presence(fields, key, label, citation_hint=""):
    value = fields.get(key)
    if nz.is_blank(value):
        return FAIL, "", f"{label} not found on any panel supplied."
    return PASS, nz.clean(value)[:280], f"{label} declared."


# ---------------------------------------------------------------------------
# Presence checks - Rule 6
# ---------------------------------------------------------------------------

@check("R01")
def manufacturer(fields, ctx):
    name = fields.get("manufacturer_name")
    addr = fields.get("manufacturer_address")
    if nz.is_blank(name) and nz.is_blank(addr):
        return FAIL, "", ("Neither the name nor the address of the manufacturer, packer or "
                          "importer was found.")
    if nz.is_blank(addr):
        return FAIL, nz.clean(name)[:280], ("A name is present but no address. The rule requires "
                                            "the name and the complete address.")
    if nz.is_blank(name):
        return FAIL, nz.clean(addr)[:280], "An address is present but no name."
    return PASS, f"{nz.clean(name)} - {nz.clean(addr)}"[:280], "Name and address declared."


@check("R02")
def country_of_origin(fields, ctx):
    if not ctx.get("is_imported"):
        return SKIP, "", "Not an imported package, so the country-of-origin declaration does not apply."
    return _presence(fields, "country_of_origin", "Country of origin")


@check("R03")
def common_name(fields, ctx):
    return _presence(fields, "common_name", "Common or generic name of the commodity")


@check("R04")
def net_quantity_present(fields, ctx):
    if ctx.get("quantity"):
        return PASS, ctx["quantity"]["text"][:280], "Net quantity declared."
    if not nz.is_blank(fields.get("net_quantity")):
        return FAIL, nz.clean(fields["net_quantity"])[:280], (
            "Text was found in the net quantity area but no readable quantity and unit could be "
            "parsed from it.")
    return FAIL, "", "Net quantity not found on any panel supplied."


@check("R05")
def manufacture_date(fields, ctx):
    value = fields.get("manufacture_date")
    if nz.is_blank(value):
        return FAIL, "", "Month and year of manufacture, packing or import not found."
    parsed = nz.parse_month_year(value)
    if not parsed["found"]:
        return FAIL, parsed["text"][:280], (
            "A date field was read but no month-and-year could be identified in it. The rule "
            "allows words, numerals or both, so this may be an extraction problem - check the "
            "stored text.")
    return PASS, parsed["text"][:280], "Month and year declared."


@check("R06")
def mrp_present(fields, ctx):
    mrp = ctx.get("mrp")
    if mrp is None or mrp["amount"] is None:
        return FAIL, nz.clean(fields.get("mrp", ""))[:280], "Retail sale price not found."
    return PASS, mrp["text"][:280], "Retail sale price declared."


@check("R07")
def consumer_care(fields, ctx):
    value = fields.get("consumer_care")
    if nz.is_blank(value):
        return FAIL, "", ("No consumer care contact found - the rule requires a name, address, "
                          "telephone number and e-mail address where available.")
    if not nz.has_contact_channel(value):
        return FAIL, nz.clean(value)[:280], (
            "A consumer care line was found but it contains no usable contact channel - no "
            "telephone number, e-mail address or postal address.")
    return PASS, nz.clean(value)[:280], "Consumer care contact declared."


# ---------------------------------------------------------------------------
# Format checks
# ---------------------------------------------------------------------------

@check("R08")
def mrp_format(fields, ctx):
    mrp = ctx.get("mrp")
    if mrp is None or mrp["amount"] is None:
        return SKIP, "", "No retail sale price to check the wording of."
    problems = []
    if not mrp["has_tax_wording"]:
        problems.append("the tax-inclusive wording is missing")
    if not mrp["has_mrp_label"]:
        problems.append("it is not labelled as maximum retail price or MRP")
    if not mrp["has_currency"]:
        problems.append("no currency is shown")
    if problems:
        return FAIL, mrp["text"][:280], (
            "Price declared as '" + mrp["text"][:80] + "' but " + "; ".join(problems) +
            ". The required form is 'MRP Rs ... inclusive of all taxes'.")
    return PASS, mrp["text"][:280], "Price is in the required form."


@check("R09")
def quantity_unit_magnitude(fields, ctx):
    q = ctx.get("quantity")
    if not q:
        return SKIP, "", "No parsable net quantity."
    if q["dimension"] not in ("mass", "volume"):
        return SKIP, q["text"][:280], "Quantity is not declared by weight or volume."
    want = nz.expected_unit(q["base"], q["dimension"])
    got = q["unit_canonical"]
    # Exactly one kilogram or one litre may be written either way.
    if q["base"] == 1000 and got in ("g", "kg", "ml", "l"):
        return PASS, q["text"][:280], "Quantity is exactly one kilogram or one litre, which may be written either way."
    if want and got != want:
        pretty = f"{q['value']:g} {got}"
        if q["dimension"] == "mass":
            alt = f"{q['base']/1000:g} kg" if want == "kg" else f"{q['base']:g} g"
        else:
            alt = f"{q['base']/1000:g} l" if want == "l" else f"{q['base']:g} ml"
        return FAIL, q["text"][:280], (
            f"Declared as '{pretty}'. At this magnitude the unit must be '{want}', so it should "
            f"read '{alt}'.")
    return PASS, q["text"][:280], "Correct unit for the magnitude declared."


@check("R10")
def si_units_only(fields, ctx):
    q = ctx.get("quantity")
    if not q:
        return SKIP, "", "No parsable net quantity."
    if q["dimension"] == "non_si":
        return FAIL, q["text"][:280], (
            f"Net quantity declared using '{q['unit_written']}', which is not an International "
            "System unit.")
    if q["unit_written"] != q["unit_canonical"] and q["unit_canonical"] is not None:
        return FAIL, q["text"][:280], (
            f"Unit written as '{q['unit_written']}' rather than the correct symbol "
            f"'{q['unit_canonical']}'.")
    return PASS, q["text"][:280], "Unit symbol is correct."


@check("R11")
def forbidden_counts(fields, ctx):
    found = nz.find_forbidden_counts(fields.get("net_quantity"), fields.get("common_name"))
    if found:
        return FAIL, ", ".join(found), (
            f"The package uses the count '{found[0]}', which may not be specified or indicated "
            "on any package.")
    return PASS, "", "No dozen, score or gross count used."


@check("R12")
def vague_quantity(fields, ctx):
    found = nz.find_vague_words(fields.get("net_quantity", ""))
    if found:
        return FAIL, ", ".join(found), (
            f"The quantity declaration contains '{found[0]}', which creates an inadequate or "
            "misleading impression of quantity.")
    return PASS, "", "Quantity declaration is stated without qualifying words."


@check("R13")
def standard_pack_size(fields, ctx):
    q = ctx.get("quantity")
    entry = ctx.get("pack_size_entry")
    if not q or q["base"] is None:
        return SKIP, "", "No parsable net quantity."
    if entry is None:
        return SKIP, q["text"][:280], (
            "This commodity is not one of those the Second Schedule specifies standard sizes for.")

    base = q["base"]
    if entry.unrestricted_below is not None and base < entry.unrestricted_below:
        return PASS, q["text"][:280], (
            f"Below {entry.unrestricted_below:g} {entry.unit}, the Schedule sets no restriction "
            f"for {entry.commodity.lower()}.")
    if base in entry.allowed():
        return PASS, q["text"][:280], f"A standard pack size for {entry.commodity.lower()}."
    if (entry.multiples_above is not None and entry.multiple_step
            and base > entry.multiples_above and base % entry.multiple_step == 0):
        return PASS, q["text"][:280], (
            f"A permitted multiple of {entry.multiple_step:g} {entry.unit} for "
            f"{entry.commodity.lower()}.")
    allowed = ", ".join(f"{a:g}" for a in entry.allowed()[:8])
    return FAIL, q["text"][:280], (
        f"{base:g} {entry.unit} is not a standard pack size for {entry.commodity.lower()}. "
        f"The Schedule permits {allowed}{' and more' if len(entry.allowed()) > 8 else ''} "
        f"{entry.unit}.")


# ---------------------------------------------------------------------------
# Informational - not a Legal Metrology rule
# ---------------------------------------------------------------------------

@check("R14")
def veg_mark(fields, ctx):
    mark = nz.clean(fields.get("veg_nonveg_mark", "")).lower()
    if mark in ("veg", "vegetarian", "green"):
        return INFO, "Vegetarian", ("Green vegetarian mark detected. Reported for information - "
                                    "this symbol sits under food safety labelling law, not the "
                                    "Legal Metrology rules.")
    if mark in ("non-veg", "nonveg", "non vegetarian", "brown", "red"):
        return INFO, "Non-vegetarian", ("Brown non-vegetarian mark detected. Reported for "
                                        "information - this symbol sits under food safety "
                                        "labelling law, not the Legal Metrology rules.")
    return INFO, "Not detected", ("No vegetarian or non-vegetarian mark detected. This is not a "
                                  "Legal Metrology requirement, so no violation is recorded.")
