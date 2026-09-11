"""Orchestration: scope first, then the checks, then a verdict."""
from . import normalize as nz
from .checks import REGISTRY

CEMENT_FERTILISER = ("cement", "fertiliser", "fertilizer", "urea", "dap ", "npk")
AGRI_PRODUCE = ("wheat", "paddy", "grain", "farm produce", "raw rice", "maize")


def check_scope(fields, quantity, manual_flags=None):
    """Rules 3 and 26 - decide whether the Rules apply to this package at all.

    Running compliance checks on an exempt package produces confident nonsense,
    so this runs before anything else. Returns a reason string when the package
    is out of scope, otherwise None.
    """
    manual_flags = manual_flags or {}
    name = nz.clean(fields.get("common_name", "")).lower()

    if manual_flags.get("restaurant_packed"):
        return "Rule 26(b) - fast food item packed by a restaurant, hotel or similar."
    if manual_flags.get("drug_price_control"):
        return ("Rule 26(c) - formulation covered by the Drugs (Price Control) Order, 1995.")
    if manual_flags.get("institutional"):
        return "Rule 3(b) - package meant for an industrial or institutional consumer."

    if quantity and quantity.get("base") is not None:
        base = quantity["base"]
        if base <= 10:
            return ("Rule 26(a) - net quantity is 10 g or 10 ml or less, so the Rules do not "
                    "apply to this package.")
        if any(k in name for k in AGRI_PRODUCE) and base > 50000:
            return "Rule 26(d) - agricultural farm produce in a package above 50 kg."
        if any(k in name for k in CEMENT_FERTILISER):
            if base > 50000:
                return ("Rule 3(a) - cement or fertiliser in a bag above 50 kg falls outside "
                        "Chapter II.")
        elif base > 25000:
            return ("Rule 3(a) - package contains more than 25 kg or 25 litres, so Chapter II "
                    "does not apply.")
    return None


def match_pack_size(fields, quantity, pack_sizes):
    """Find the Second Schedule row for this commodity, if there is one."""
    if not quantity or quantity.get("dimension") not in ("mass", "volume"):
        return None
    haystack = " ".join([
        nz.clean(fields.get("common_name", "")).lower(),
        nz.clean(fields.get("product_name", "")).lower(),
    ])
    if not haystack.strip():
        return None
    want_unit = "g" if quantity["dimension"] == "mass" else "ml"
    best, best_len = None, 0
    for entry in pack_sizes:
        if entry.unit != want_unit:
            continue
        for kw in entry.keyword_list():
            if kw and kw in haystack and len(kw) > best_len:
                best, best_len = entry, len(kw)
    return best


def evaluate(fields, rules, pack_sizes, is_imported=False, manual_flags=None):
    """Run every active rule against the merged fields.

    Returns (verdict, exempt_reason, results) where results is a list of dicts
    ready to be written as Violation rows.
    """
    quantity = nz.parse_quantity(fields.get("net_quantity", ""))
    mrp = nz.parse_mrp(fields.get("mrp", ""))

    exempt_reason = check_scope(fields, quantity, manual_flags)
    if exempt_reason:
        return "EXEMPT", exempt_reason, []

    ctx = {
        "is_imported": is_imported,
        "quantity": quantity,
        "mrp": mrp,
        "pack_size_entry": match_pack_size(fields, quantity, pack_sizes),
    }

    results, failed, incomplete = [], False, False
    for rule in rules:
        fn = REGISTRY.get(rule.code)
        if fn is None:
            continue
        try:
            status, observed, message = fn(fields, ctx)
        except Exception as exc:                      # a broken check must not sink the scan
            status, observed, message = "SKIP", "", f"Check could not be run: {exc}"
        if status == "FAIL":
            failed = True
        elif status == "RECHECK":
            incomplete = True
        results.append({
            "rule": rule,
            "status": status,
            "severity": rule.severity,
            "observed": observed or "",
            "message": message,
        })

    # A violation outranks an incomplete check: finding a real breach does not
    # become less true because some other declaration sits on an unseen panel.
    # But we never call a label compliant while a mandatory declaration has gone
    # unread - that is how a scanner ends up confidently wrong.
    if failed:
        verdict = "NON_COMPLIANT"
    elif incomplete:
        verdict = "INCOMPLETE"
    else:
        verdict = "COMPLIANT"
    return verdict, "", results