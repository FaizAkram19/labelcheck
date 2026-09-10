# Label compliance check — SIH26034

Photograph a packaged product's label, get back a report naming every Legal
Metrology violation and the rule it breaks.

Problem statement SIH26034, Ministry of Consumer Affairs, Food & Public
Distribution. Built for the internal round on 12 September 2026.

---

## The one idea worth remembering

**The model reads. The engine judges.**

A vision model transcribes the label into fields and does nothing else. Every
pass and fail is decided by explicit Python in `compliance/engine/`, against
rules stored as database rows. The transcription is saved next to the verdict,
so any finding can be traced back to the text it came from.

That is why the same label always produces the same result, and it is the answer
to "how do you know the AI isn't making this up".

---

## Running it

Nothing here costs money. Free-tier extraction API, SQLite, your own laptop.

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                                   # then paste your key into .env

python manage.py migrate
python manage.py seed_rules        # the 14 rules + Second Schedule pack sizes
python manage.py seed_demo         # 8 offline examples so the app is not empty
python manage.py check_key         # lists usable models, then tests the key
python manage.py runserver 0.0.0.0:8000
```

### About the API key

Keys created in Google AI Studio now start with `AQ.` — these are authorization
keys, bound to a service account. That is the current format and it is correct;
the older `AIza` standard keys are being retired.

The key is sent in an `x-goog-api-key` header, not as a `?key=` URL parameter.
`AQ.` keys reject the URL form, and a secret in a URL ends up in logs anyway.

Model names change. `check_key` asks the API which models your key can actually
reach and tells you what to put in `GEMINI_MODEL` — don't copy a model name out
of a tutorial.

Open `http://localhost:8000`. For the admin, `python manage.py createsuperuser`
first, then `http://localhost:8000/admin/`.

### Using a phone against your laptop

Both devices on the same wifi. Find the laptop's address with `ipconfig`
(Windows) or `ifconfig | grep inet` (Mac/Linux), then open
`http://<that-address>:8000` on the phone.

Camera capture needs a secure context in most browsers. On plain `http://` over
a local network, Chrome on Android will still let the user pick or take a photo
through the file input, which is what this app uses. If a browser refuses, use
a tunnel — ngrok's free tier is enough and costs nothing.

---

## Layout

```
compliance/
  models.py              Rule, StandardPackSize, Scan, ScanImage, ExtractedData, Violation
  engine/
    normalize.py         quantity and price parsing — pure functions, heavily tested
    checks.py            one function per rule, registered by code
    runner.py            scope exclusions, then every check, then the verdict
  extraction/
    prompt.py            the transcription prompt
    gemini.py            the single network call
  management/commands/
    seed_rules.py        the rule catalogue
    seed_demo.py         offline examples
    check_key.py         first-run key test
  views.py               five endpoints
templates/app.html       the whole frontend, one file, no build step
```

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health/` | rules loaded, whether a key is present, scan count |
| GET | `/api/rules/` | the active rule catalogue |
| POST | `/api/scans/create/` | `images` (1–2 files), optional `panels`, exemption flags |
| GET | `/api/scans/` | history |
| GET | `/api/scans/<id>/` | full report |
| POST | `/api/scans/<id>/recheck/` | re-run rules on stored extraction — no network call |

`recheck` matters: when a rule is corrected after verification, every past scan
can be re-evaluated against the fixed catalogue without rescanning anything.

## Rules implemented

Twelve checks plus one informational. Presence of the mandatory declarations
under Rule 6; the retail sale price wording from Rule 2(m); unit correctness from
Rule 13; qualifying words from Rule 12(6); standard pack sizes from Rule 5 and the
Second Schedule. Exclusions under Rules 3 and 26 run first, so an exempt package
is never reported as non-compliant.

Every rule row starts with `verified = False`. Tick it in the admin as the
research pair returns the sign-off sheet. The report shows a warning on any
finding whose citation is still unverified.

**Not checked, and said so on the limitations slide:** minimum letter heights
(Rule 7), position on the principal display panel (Rule 8), contrasting colour
and language (Rule 9), and physical net-quantity testing (Rules 19–23). These
need measurement or a weighing instrument, which a photograph cannot provide.

## Tests

```bash
python manage.py test compliance
```

25 tests covering the engine — presence, formats, pack sizes, scope exclusions,
and a blank label. No network, no images. They run in under a second, so run them
after any change to `engine/`.

## Demo day

Seeded examples and every real scan replay from the database with no network
call. If the venue connection dies, open a stored check from the history and the
demo continues. Scan a few real products in the morning so the history holds
genuine results rather than seeded ones.
