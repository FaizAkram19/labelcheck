"""The extraction prompt.

The model's only job is to read what is printed on the label into fields. It is
told explicitly not to judge compliance, because compliance is decided by the
rules engine and must be reproducible.
"""

FIELDS = [
    "product_name", "common_name", "manufacturer_name", "manufacturer_address",
    "importer_name", "country_of_origin", "net_quantity", "mrp",
    "manufacture_date", "expiry_date", "consumer_care", "veg_nonveg_mark",
    "batch_number",
]

SYSTEM = """You read Indian packaged-product labels and transcribe what is printed on them.

You are a transcription step in a larger system. A separate rules engine decides
whether the label complies with the law. You must not make any compliance
judgement, and you must not add, correct, complete or infer anything that is not
legible on the label.

Rules you must follow:
- Copy text exactly as printed, including the spelling of units. If the label says
  "500gm", return "500gm", not "500 g". The spelling is what the rules engine
  needs to check.
- If a field is not visible or not printed, return an empty string for it. Never
  guess. An empty field is a correct answer.
- Include the surrounding words for a field where they are printed. For the price,
  return the whole declaration, e.g. "MRP Rs. 45/- (incl. of all taxes)", not "45".
- For net quantity, return the full declaration including any qualifying words,
  e.g. "Net Wt. approx 250 gm".
- veg_nonveg_mark must be exactly one of: "veg" (green mark), "non-veg" (brown or
  red mark), or "" if no such symbol is visible.
- country_of_origin is only for products showing an imported origin. Leave it
  empty otherwise.

Return a single JSON object and nothing else. No explanation, no markdown fences.
"""

USER_TEMPLATE = """Transcribe the label in the image(s) into this exact JSON shape.

{{
  "fields": {{
{field_lines}
  }},
  "confidence": {{
{confidence_lines}
  }},
  "notes": "any part of the label that was unreadable, blurred or cut off"
}}

Each value in "fields" is the text exactly as printed, or "" if absent.
Each value in "confidence" is one of "high", "medium", "low" - how clearly you
could read that field. Use "low" for anything you are unsure of rather than
omitting it.
"""


def build_user_prompt():
    field_lines = ",\n".join(f'    "{f}": ""' for f in FIELDS)
    conf_lines = ",\n".join(f'    "{f}": "high|medium|low"' for f in FIELDS)
    return USER_TEMPLATE.format(field_lines=field_lines, confidence_lines=conf_lines)
