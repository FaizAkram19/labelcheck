"""Engine tests. No network, no images - just fields in, verdict out."""
from django.core.management import call_command
from django.test import TestCase

from .engine.runner import evaluate
from .models import Rule, StandardPackSize


def blank():
    return {k: "" for k in [
        "product_name", "common_name", "manufacturer_name", "manufacturer_address",
        "importer_name", "country_of_origin", "net_quantity", "mrp",
        "manufacture_date", "expiry_date", "consumer_care", "veg_nonveg_mark",
        "batch_number"]}


def good_biscuit():
    f = blank()
    f.update({
        "product_name": "Krisp Marie",
        "common_name": "Marie Biscuits",
        "manufacturer_name": "Krisp Foods Pvt Ltd",
        "manufacturer_address": "Plot 14, MIDC, Pune 411019",
        "net_quantity": "Net Wt. 200 g",
        "mrp": "MRP Rs. 30.00 (inclusive of all taxes)",
        "manufacture_date": "Mfd: 06/2026",
        "consumer_care": "care@krispfoods.in, 1800 123 4567",
        "veg_nonveg_mark": "veg",
    })
    return f


class EngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_rules", verbosity=0)
        cls.rules = list(Rule.objects.filter(active=True))
        cls.packs = list(StandardPackSize.objects.all())

    def run_engine(self, fields, **kw):
        return evaluate(fields, self.rules, self.packs, **kw)

    def statuses(self, results):
        return {r["rule"].code: r["status"] for r in results}

    def message(self, results, code):
        return next(r["message"] for r in results if r["rule"].code == code)

    # ---------------------------------------------------------------- happy path
    def test_fully_compliant_label_passes(self):
        verdict, _, results = self.run_engine(good_biscuit())
        st = self.statuses(results)
        self.assertEqual(verdict, "COMPLIANT")
        for code in ["R01", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10"]:
            self.assertEqual(st[code], "PASS", f"{code}: {self.message(results, code)}")
        self.assertEqual(st["R02"], "SKIP")     # not imported
        self.assertEqual(st["R14"], "INFO")     # veg mark never a violation

    # ---------------------------------------------------------------- presence
    def test_missing_mrp_and_consumer_care_are_major(self):
        f = good_biscuit()
        f["mrp"] = ""
        f["consumer_care"] = ""
        verdict, _, results = self.run_engine(f)
        st = self.statuses(results)
        self.assertEqual(verdict, "NON_COMPLIANT")
        self.assertEqual(st["R06"], "FAIL")
        self.assertEqual(st["R07"], "FAIL")
        self.assertEqual(st["R08"], "SKIP")     # nothing to check the wording of

    def test_name_without_address_fails(self):
        f = good_biscuit()
        f["manufacturer_address"] = ""
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R01"], "FAIL")
        self.assertIn("no address", self.message(results, "R01"))

    def test_consumer_care_without_a_channel_fails(self):
        f = good_biscuit()
        f["consumer_care"] = "Customer Care Department"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R07"], "FAIL")

    def test_unparseable_date_fails(self):
        f = good_biscuit()
        f["manufacture_date"] = "Best before 9 months"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R05"], "FAIL")

    # ---------------------------------------------------------------- imported
    def test_imported_without_country_of_origin_fails(self):
        f = good_biscuit()
        f["importer_name"] = "Global Imports Pvt Ltd"
        _, _, results = self.run_engine(f, is_imported=True)
        self.assertEqual(self.statuses(results)["R02"], "FAIL")

    def test_imported_with_country_of_origin_passes(self):
        f = good_biscuit()
        f["country_of_origin"] = "Country of Origin: Malaysia"
        _, _, results = self.run_engine(f, is_imported=True)
        self.assertEqual(self.statuses(results)["R02"], "PASS")

    # ---------------------------------------------------------------- format
    def test_mrp_without_tax_wording_is_minor(self):
        f = good_biscuit()
        f["mrp"] = "Rs. 30"
        verdict, _, results = self.run_engine(f)
        st = self.statuses(results)
        self.assertEqual(st["R06"], "PASS")     # present
        self.assertEqual(st["R08"], "FAIL")     # but wrongly worded
        self.assertEqual(verdict, "NON_COMPLIANT")

    def test_gm_instead_of_g_is_flagged(self):
        f = good_biscuit()
        f["net_quantity"] = "Net Wt. 200gm"
        _, _, results = self.run_engine(f)
        st = self.statuses(results)
        self.assertEqual(st["R10"], "FAIL")
        self.assertEqual(st["R09"], "PASS")     # magnitude is right, spelling is not

    def test_wrong_unit_for_magnitude(self):
        f = good_biscuit()
        f["common_name"] = "Refined Sunflower Oil"
        f["net_quantity"] = "1500 g"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R09"], "FAIL")
        self.assertIn("1.5 kg", self.message(results, "R09"))

    def test_half_kilogram_written_as_kg_is_flagged(self):
        f = good_biscuit()
        f["net_quantity"] = "0.5 kg"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R09"], "FAIL")
        self.assertIn("500 g", self.message(results, "R09"))

    def test_exactly_one_kilogram_may_be_written_either_way(self):
        f = good_biscuit()
        f["common_name"] = "Atta"
        for written in ["1 kg", "1000 g"]:
            f["net_quantity"] = written
            _, _, results = self.run_engine(f)
            self.assertEqual(self.statuses(results)["R09"], "PASS", written)

    def test_non_si_unit_fails(self):
        f = good_biscuit()
        f["net_quantity"] = "Net Wt. 8 oz"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R10"], "FAIL")

    def test_dozen_is_forbidden(self):
        f = good_biscuit()
        f["net_quantity"] = "1 dozen pieces"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R11"], "FAIL")

    def test_approx_on_quantity_fails(self):
        f = good_biscuit()
        f["net_quantity"] = "Net Wt. approx 200 g"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R12"], "FAIL")

    # ---------------------------------------------------------------- schedule
    def test_non_standard_biscuit_pack_size_fails(self):
        f = good_biscuit()
        f["net_quantity"] = "Net Wt. 180 g"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R13"], "FAIL")
        self.assertIn("biscuits", self.message(results, "R13"))

    def test_standard_biscuit_pack_size_passes(self):
        _, _, results = self.run_engine(good_biscuit())
        self.assertEqual(self.statuses(results)["R13"], "PASS")

    def test_unscheduled_commodity_is_skipped(self):
        f = good_biscuit()
        f["common_name"] = "Steel Wool Scrubber"
        f["product_name"] = "ShineMax"
        f["net_quantity"] = "37 g"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R13"], "SKIP")

    def test_salt_below_fifty_grams_unrestricted(self):
        f = good_biscuit()
        f["common_name"] = "Iodised Salt"
        f["product_name"] = "Salt"
        f["net_quantity"] = "30 g"
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R13"], "PASS")

    # ---------------------------------------------------------------- scope
    def test_sachet_under_ten_grams_is_exempt(self):
        f = good_biscuit()
        f["net_quantity"] = "8 g"
        f["mrp"] = ""
        verdict, reason, results = self.run_engine(f)
        self.assertEqual(verdict, "EXEMPT")
        self.assertIn("Rule 26(a)", reason)
        self.assertEqual(results, [])

    def test_bulk_pack_over_twentyfive_kg_is_exempt(self):
        f = good_biscuit()
        f["common_name"] = "Refined Oil"
        f["net_quantity"] = "30 kg"
        verdict, reason, _ = self.run_engine(f)
        self.assertEqual(verdict, "EXEMPT")
        self.assertIn("Rule 3(a)", reason)

    def test_cement_bag_up_to_fifty_kg_still_checked(self):
        f = good_biscuit()
        f["common_name"] = "Portland Cement"
        f["net_quantity"] = "50 kg"
        verdict, reason, results = self.run_engine(f)
        self.assertNotEqual(verdict, "EXEMPT")
        self.assertTrue(results)

    def test_restaurant_flag_exempts(self):
        verdict, reason, _ = self.run_engine(
            good_biscuit(), manual_flags={"restaurant_packed": True})
        self.assertEqual(verdict, "EXEMPT")
        self.assertIn("Rule 26(b)", reason)

    # ---------------------------------------------------------------- robustness
    def test_completely_blank_label_does_not_crash(self):
        verdict, _, results = self.run_engine(blank())
        self.assertEqual(verdict, "NON_COMPLIANT")
        self.assertTrue(any(r["status"] == "FAIL" for r in results))

    def test_every_active_rule_produces_a_result(self):
        _, _, results = self.run_engine(good_biscuit())
        self.assertEqual(len(results), len(self.rules))


class CrossReferenceTests(EngineTests):
    """A declaration printed elsewhere on the pack is not a missing declaration."""

    def test_price_pointing_to_the_bottom_is_not_a_violation(self):
        f = good_biscuit()
        f["mrp"] = "See bottom for MRP Rs. (incl. of all taxes)"
        verdict, _, results = self.run_engine(f)
        st = self.statuses(results)
        self.assertEqual(st["R06"], "RECHECK")
        self.assertEqual(st["R08"], "SKIP")
        self.assertEqual(verdict, "INCOMPLETE")

    def test_net_quantity_pointing_to_coding_area(self):
        f = good_biscuit()
        f["net_quantity"] = "NET WT. (WHEN PACKED) : SEE CODING AREA."
        verdict, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R04"], "RECHECK")
        self.assertEqual(verdict, "INCOMPLETE")

    def test_packing_date_pointing_to_the_bottom(self):
        f = good_biscuit()
        f["manufacture_date"] = "See bottom for PKD."
        _, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R05"], "RECHECK")

    def test_a_real_violation_still_outranks_an_incomplete_check(self):
        f = good_biscuit()
        f["mrp"] = "See bottom for MRP"
        f["consumer_care"] = ""
        verdict, _, results = self.run_engine(f)
        st = self.statuses(results)
        self.assertEqual(st["R06"], "RECHECK")
        self.assertEqual(st["R07"], "FAIL")
        self.assertEqual(verdict, "NON_COMPLIANT")

    def test_genuinely_missing_price_is_still_a_violation(self):
        f = good_biscuit()
        f["mrp"] = ""
        verdict, _, results = self.run_engine(f)
        self.assertEqual(self.statuses(results)["R06"], "FAIL")
        self.assertEqual(verdict, "NON_COMPLIANT")

    def test_normal_labels_are_unaffected(self):
        verdict, _, results = self.run_engine(good_biscuit())
        self.assertEqual(verdict, "COMPLIANT")
        self.assertNotIn("RECHECK", self.statuses(results).values())