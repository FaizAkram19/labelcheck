"""Parsing helpers.

Everything here is deterministic string and number handling. No model calls,
no network. Given the same text it always returns the same result, which is
what makes the compliance verdict reproducible.
"""
import re

# Unit symbols the rules permit for net quantity, mapped to a base unit.
MASS_UNITS = {"g": 1.0, "kg": 1000.0}
VOLUME_UNITS = {"ml": 1.0, "l": 1000.0}

# Common non-SI or malformed abbreviations seen on Indian packaging, mapped to
# what the writer meant. Rule 13(5)(i) allows only International System units.
BAD_UNIT_ALIASES = {
    "gm": "g", "gms": "g", "gm.": "g", "grm": "g", "grms": "g", "gr": "g",
    "kgs": "kg", "kg.": "kg", "kgm": "kg",
    "ltr": "l", "ltrs": "l", "lt": "l", "lts": "l", "litre": "l", "litres": "l",
    "liter": "l", "liters": "l", "ltr.": "l",
    "mltr": "ml", "mls": "ml", "m.l": "ml", "cc": "ml",
    "oz": None, "lb": None, "lbs": None, "gal": None, "fl.oz": None, "pound": None,
}

# Rule 13(4) - none of these counts may appear on a package.
FORBIDDEN_COUNTS = ["dozen", "score", "gross", "great gross"]

# Rule 12(6) - words that create an exaggerated or inadequate impression of quantity.
VAGUE_QUANTITY_WORDS = [
    "minimum", "min.", "not less than", "average", "avg", "about",
    "approximately", "approx", "approx.", "at least", "upto", "up to",
]

MRP_TAX_PHRASES = [
    "inclusive of all taxes", "incl. of all taxes", "incl of all taxes",
    "inclusive of all tax", "incl. all taxes", "inclusive of taxes",
    "including all taxes", "inc. of all taxes",
]
MRP_LABELS = ["mrp", "m.r.p", "maximum retail price", "max retail price",
              "max. retail price", "retail price"]

_NUM = r"(\d+(?:[.,]\d+)?)"


def clean(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def is_blank(text):
    """True when a field is missing in any of the ways a model reports it."""
    t = clean(text).lower().strip(" .:-")
    return t in {"", "none", "null", "n/a", "na", "not found", "not visible",
                 "not present", "unknown", "-", "--"}


def parse_quantity(text):
    """Pull a net quantity out of free text.

    Returns a dict describing what was written and what it means, or None when
    no quantity can be found. `unit_written` preserves the label's own spelling
    so the format checks can object to it.
    """
    t = clean(text).lower().replace("\u00a0", " ")
    if not t:
        return None

    # Longest unit tokens first so "ml" is not matched inside "mltr".
    tokens = sorted(
        set(list(MASS_UNITS) + list(VOLUME_UNITS) + [k for k in BAD_UNIT_ALIASES]),
        key=len, reverse=True,
    )
    pattern = _NUM + r"\s*(" + "|".join(re.escape(u) for u in tokens) + r")\b"
    m = re.search(pattern, t)
    if not m:
        m2 = re.search(_NUM + r"\s*(n|u)\b", t)
        if m2:
            return {"value": float(m2.group(1).replace(",", ".")),
                    "unit_written": m2.group(2), "unit_canonical": "N",
                    "dimension": "number", "base": None, "text": clean(text)}
        return None

    value = float(m.group(1).replace(",", "."))
    written = m.group(2)

    canonical = written
    if written in BAD_UNIT_ALIASES:
        canonical = BAD_UNIT_ALIASES[written]
    if canonical is None:
        return {"value": value, "unit_written": written, "unit_canonical": None,
                "dimension": "non_si", "base": None, "text": clean(text)}

    if canonical in MASS_UNITS:
        dimension, base = "mass", value * MASS_UNITS[canonical]
    elif canonical in VOLUME_UNITS:
        dimension, base = "volume", value * VOLUME_UNITS[canonical]
    else:
        dimension, base = "other", None

    return {"value": value, "unit_written": written, "unit_canonical": canonical,
            "dimension": dimension, "base": base, "text": clean(text)}


def expected_unit(base, dimension):
    """Rule 13(2) and 13(3): which symbol the magnitude requires."""
    if base is None:
        return None
    if dimension == "mass":
        return "g" if base < 1000 else "kg"
    if dimension == "volume":
        return "ml" if base < 1000 else "l"
    return None


def parse_mrp(text):
    """Read a retail sale price declaration.

    Reports the amount and whether the tax-inclusive wording required by the
    definition of 'retail sale price' is present.
    """
    raw = clean(text)
    t = raw.lower()
    if not raw:
        return None
    m = re.search(r"(?:rs\.?|inr|₹)\s*" + _NUM, t) or re.search(_NUM, t)
    amount = float(m.group(1).replace(",", "")) if m else None
    return {
        "amount": amount,
        "has_tax_wording": any(p in t for p in MRP_TAX_PHRASES),
        "has_mrp_label": any(p in t for p in MRP_LABELS),
        "has_currency": bool(re.search(r"rs\.?|inr|₹", t)),
        "text": raw,
    }


def find_forbidden_counts(*texts):
    joined = " ".join(clean(t).lower() for t in texts if t)
    return [w for w in FORBIDDEN_COUNTS if re.search(r"\b" + re.escape(w) + r"\b", joined)]


def find_vague_words(text):
    t = clean(text).lower()
    return [w for w in VAGUE_QUANTITY_WORDS if w in t]


def parse_month_year(text):
    """Rule 6(1)(d) allows words, numerals, or both. Accept all three."""
    t = clean(text).lower()
    if not t:
        return None
    months = ("jan feb mar apr may jun jul aug sep oct nov dec")
    if re.search(r"\b(" + "|".join(months.split()) + r")[a-z]*\.?\s*,?\s*(19|20)?\d{2}\b", t):
        return {"found": True, "text": clean(text)}
    if re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-.]\s*((19|20)?\d{2})\b", t):
        return {"found": True, "text": clean(text)}
    if re.search(r"\b(19|20)\d{2}\s*[/\-.]\s*(0?[1-9]|1[0-2])\b", t):
        return {"found": True, "text": clean(text)}
    return {"found": False, "text": clean(text)}


def has_contact_channel(text):
    """Rule 6(2) wants a way to reach someone: phone, e-mail or a postal address."""
    t = clean(text).lower()
    if not t:
        return False
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t):
        return True
    if re.search(r"(\+?91[\s-]?)?\d{10}\b|\b1800[\s-]?\d{3}[\s-]?\d{4}\b|\b0\d{2,4}[\s-]?\d{6,8}\b", t):
        return True
    if re.search(r"\b\d{6}\b", t):  # PIN code implies a postal address
        return True
    return len(t) > 25 and any(k in t for k in ["road", "street", "nagar", "po ", "p.o", "dist"])
