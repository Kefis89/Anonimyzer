# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Local Russian-language PII (ПДн) anonymizer. Input: a Russian string. Output: the same string
with PII replaced by flat labels (`[Имя]`, `[Телефон]`, `[Адрес]`, ...). Goal: safely send the
anonymized text to external cloud LLMs without leaking the originals.

Three design principles drive every decision — keep them in mind before changing anything:
- **Irreversible**: replacement is one-way, there is no mapping table to restore originals.
- **Recall over precision**: missing a piece of PII is the worst outcome. Over-masking (masking
  a non-PII token) is acceptable. When in doubt, mask.
- **Strictly local**: all detection runs on the machine. The only network call is to a *local*
  LMStudio server (`localhost:1234`).

There is also a detailed user-facing guide in `DOCUMENTATION_RU.md` (Russian) and its English
translation `DOCUMENTATION_EN.md` (purpose, install, LM Studio setup, deployment, API, per-detector
internals, repo layout). They overlap this file — when you change structure, commands, file names,
or the public API, update both `DOCUMENTATION_RU.md` and `DOCUMENTATION_EN.md` too so they don't drift.

## Environment constraint (important)

**Never auto-install dependencies or download models in this repo.** Only create/use the venv at
`.venv`. When new packages or spaCy/Natasha models are needed, hand the exact install commands to
the user and let them run them. The heavy deps (natasha, presidio-analyzer, spaCy `ru_core_news_lg`,
LMStudio) are already installed by the user; do not reinstall or download them.

Optional Python deps and what they enable (degrade gracefully if absent):
- `fastapi` + `uvicorn[standard]` — the HTTP API (`anonymizer/api.py`, `tests/test_api.py`).
- `httpx` — required by FastAPI's `TestClient` in `tests/test_api.py`.
- `python-dotenv` — lets `api.py` read `.env`; without it real env vars are used directly.

## Commands

All commands assume the venv interpreter: `.venv\Scripts\python.exe` (Windows / PowerShell).

```powershell
# Run the full test suite
.venv\Scripts\python.exe -m pytest -v

# Run a single test file / class / case
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py -v
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py::TestCollapseRepeatedLabels -v
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py::TestRegexStructuredIDs::test_email -v

# Demo: prints ДО / ПОСЛЕ / ДЕТЕКТОРЫ for built-in examples
.venv\Scripts\python.exe -m anonymizer

# Run the HTTP API server (listens on 127.0.0.1:8077 by default)
.venv\Scripts\python.exe run.py        # entrypoint; `python -m anonymizer.api` also works

# Standalone API smoke client (stdlib only)
.venv\Scripts\python.exe client_example.py
```

There is no build step and no linter configured.

## Architecture

### Pipeline (`anonymizer/pipeline.py`)

`anonymize_detailed(text)` is the orchestrator. Order matters:

1. **Detect** — run every detector in `DETECTORS`, collecting `Span`s. Each detector's raw count
   is recorded in `spans_found` (this is the per-detector statistic exposed in the API/demo;
   it is counted *before* merging and is *not* affected by later text post-processing).
2. **`split_persons`** — decompose `person` spans into `name`/`surname`/`patronymic`.
3. **`merge_spans`** — resolve overlaps and glue address fragments.
4. **`apply_spans`** — replace spans with labels.
5. **`verify_with_llm`** — LLM re-reads the masked text to catch leftover PII (up to
   `max_verify_passes`).
6. **`relabel_groups`** — text-only step: rewrite fine labels into coarse groups per
   `config.LABEL_GROUPS` (`[Имя]`/`[Фамилия]`/`[Отчество]` → `[ФИО]`, `[Локация]` → `[Адрес]`).
   After this, the fine labels no longer appear in output; runs after verify so it also normalizes
   verify-added labels, and it does not touch detection or merge priorities.
7. **`collapse_repeated_labels`** — final text-only step: collapse runs of *identical* adjacent
   labels (`[X] [X]` → `[X]`); different neighbors are left alone.

`anonymize(text)` is the thin wrapper returning just `.text`. `anonymize_detailed` also takes
optional `detectors=None` (default: all detectors enabled in `config.DETECTORS_ENABLED`; a
disabled detector is skipped and absent from `spans_found`) and keyword-only `verify=True`
(toggle the LLM verify pass). An explicitly passed detector list bypasses the config filter —
the per-detector API endpoint and the eval scripts call
`anonymize_detailed(text, [one_detector], verify=False)` to isolate a single detector even if it
is disabled in config. `DETECTOR_LLM = False` also disables the verify pass (checked inside
`verify_with_llm`). Spans of
types disabled via `ANONYMIZE_TYPES`, and spans whose **source detector is not allowed to replace
that type** via `DETECTOR_TYPES`, are dropped **before merge** (see Configuration), both here and
inside `verify_with_llm`. The `DETECTOR_TYPES` per-detector type filter applies on **every** path,
including an explicit detector list — it is *not* bypassed the way the `DETECTORS_ENABLED` on/off
filter is.

### Detector ensemble (`anonymizer/detectors/`)

Four independent detectors, registered (in order) in `detectors/__init__.py` as
`DETECTORS = [regex, natasha, presidio, llm]`. Each module is a uniform plugin:

- `NAME: str` — `"regex"` / `"natasha"` / `"presidio"` / `"llm"`.
- `detect(text) -> list[Span]` — **fault-tolerant**: returns `[]` if unavailable; never raises.
- `available() -> bool`.

**Order is significant**: at equal `PRIORITY`, the detector listed first "paints" its chars first
in `merge_spans`, so regex/structural detectors come before the model-based ones.

Roles:
- **regex** (`regex.py`) — structured IDs via patterns in `config.REGEXES`. Always available.
- **natasha** (`natasha.py`) — NER (PER/LOC/ORG) + rule extractors (address/date/money).
- **presidio** (`presidio.py`) — spaCy `ru_core_news_lg` NER + custom RU-ID pattern recognizers.
- **llm** (`llm.py`) — LLM via LMStudio, for contextual recall of *semantic* entities only.

### Eager loading (no lazy init)

Detector models load **at import time**, not on first use: `natasha.NATASHA`, `presidio.PRESIDIO`,
and `llm.LMSTUDIO_MODEL` are module-level globals assigned during import. Consequences:
- `import anonymizer` is slow and has side effects, including a network probe to `localhost:1234`
  (fast `connection refused` if LMStudio is down, so import won't hang).
- A missing library/model sets its global to `None` and silently disables that detector — the
  pipeline keeps running on the rest.
- **Tests/mocks must patch these module-level globals** (e.g. `monkeypatch.setattr(llm,
  "LMSTUDIO_MODEL", None)`), which is exactly how `tests/test_anonymizer.py` forces determinism.

### Span model & merge (`span.py`, `merge.py`)

`Span(start, stop, type, source)` is a half-open `[start, stop)` interval; `type` is a key into
both `LABELS` and `PRIORITY` (`config.py`).

`merge_spans` resolves overlaps by **char-painting**: each character is owned by the highest-
`PRIORITY` type covering it, then adjacent same-type runs become spans. This handles partial
overlaps cleanly. Afterward, adjacent `address` fragments separated only by punctuation/space are
**glued** into one (`AddrExtractor` splits an address into `г. Уфа` / `ул. Ленина` / `д. 5`).

`PRIORITY` (in `config.py`) encodes the conflict policy: structured IDs (email/phone/card/ip/
passport/snils=100, inn=95) and name components (90) beat address (80), person (70), money (60),
org (50), loc (40), date (30). Change `PRIORITY` to change which label wins on overlap.

`apply_spans` replaces from the end of the string backward (so offsets stay valid) and trims
whitespace at span edges (otherwise a captured trailing space gets swallowed and adjacent labels
fuse, e.g. `[Сумма][Дата]`).

### Person decomposition (`persons.py`)

`NamesExtractor` is unreliable on free text (mislabels job titles as surnames), so it is run
**only on the substring of an already-confirmed `person` span**. It returns inflected surface forms
without offsets; positions are recovered via `\b...\b` word-boundary search inside the span (`\w`
matches Cyrillic in Python). If decomposition fails, the span stays `[ФИО]` (fallback).

## Non-obvious gotchas (don't "fix" these)

These guard against real false-matches discovered during development:

- **Passport regex requires a separator** between series and number; otherwise it matches a bare
  10-digit INN and mislabels it.
- **Money regex requires a currency** (symbol or word); otherwise bare numbers (INN, postal codes)
  become `[Сумма]`.
- **Presidio's `PhoneRecognizer` is removed from the registry** — `phonenumbers` greedily matches
  bare digit groups (INN/passport) as phones, and phone outranks INN, producing `[Телефон]` where
  `[ИНН]` belongs. RU phones (`+7`/`8`) are handled by the regex detector instead.
- **Presidio's `EmailRecognizer` is NOT registered** — its `validate_result` calls `tldextract`,
  which on a cold cache makes an HTTPS request to fetch the public suffix list, breaking the
  "strictly local" principle. Emails are owned by the regex detector (same priority 100).
- **LLM never returns structured IDs** (`config.LLM_SKIP_TYPES`). It confuses СНИЛС/телефон,
  ИНН/паспорт, etc.; those are owned deterministically by regex/Presidio. LLM's job is semantic
  recall: names, orgs, locations, addresses, dates, money.
- **The LLM is not pinned to a specific model.** `llm._detect_model()` probes `GET /v1/models`
  and uses whatever model LMStudio has loaded (`LMSTUDIO["model"] or models[0]["id"]`); `NAME` is
  just the `"llm"` label. Requirements the model must meet (see DOCUMENTATION §4): an
  OpenAI-compatible chat endpoint, **structured output** (`response_format` must be `json_schema`,
  NOT `json_object`, which LMStudio rejects with HTTP 400), and good enough Russian to return
  verbatim Russian substrings (otherwise `text.find` drops them, lowering recall).
- **Reasoning models put the JSON in `reasoning_content`.** With a schema response the answer often
  arrives in `reasoning_content` with an empty `content`, so reads fall back:
  `msg.get("content") or msg.get("reasoning_content")` — works for both reasoning and plain models.
- **setuptools must stay <81 in the venv** — pymorphy2 (natasha's dependency) discovers its
  dictionaries via `pkg_resources`, removed in setuptools>=82; with newer setuptools
  `MorphVocab()` raises ModuleNotFoundError and the whole natasha detector silently disables
  (tests skip instead of failing). Do not "fix" this by patching the natasha detector module —
  pin setuptools instead (`pip install "setuptools<81"`).

## Configuration (`config.py`)

Everything tunable lives here, separate from logic: `LABELS`, `PRIORITY`, `REGEXES`
(`_MONEY_*` building blocks compose the money pattern), `LMSTUDIO` settings, `LLM_SKIP_TYPES`,
and `API` defaults. The API host/port/key are overridable via env vars `ANONYMIZER_HOST` /
`ANONYMIZER_PORT` / `ANONYMIZER_API_KEY` (loaded from `.env` if `python-dotenv` is installed).

Per-type masking switches: `ANONYMIZE_<TYPE>` constants (one per span type) feed the
`ANONYMIZE_TYPES` dict; `is_type_enabled(type)` is the runtime check. The pipeline drops spans of
disabled types **before merge** (in `anonymize_detailed` and in `verify_with_llm`), so a disabled
type is not masked — but it is still *detected* (`spans_found` counts are unaffected). All default
to `True` except `ANONYMIZE_MONEY = False` and `ANONYMIZE_DATE = False` (sums and dates are
intentionally left unmasked).

Final label grouping: `LABEL_GROUPS` (type → type) drives the `relabel_groups` text step (see
Pipeline step 6) — `name`/`surname`/`patronymic` → `person` (`[ФИО]`) and `loc` → `address`
(`[Адрес]`). It is presentation-only (runs last, after verify; doesn't affect detection or merge),
so the fine labels never appear in final output. `collapse_repeated_labels` then merges adjacent
identical labels separated by whitespace only. Set `LABEL_GROUPS = {}` to disable grouping.

Per-detector switches, same pattern: `DETECTOR_<NAME>` constants feed `DETECTORS_ENABLED`;
`is_detector_enabled(name)` is the runtime check. A disabled detector is excluded from the
*default* detector set only (see Pipeline above); explicit lists bypass the filter, and models
still load eagerly at import. All default to `True`.

Per-detector **type** allowlist, same pattern: `DETECTOR_<NAME>_TYPES` sets feed the
`DETECTOR_TYPES` dict; `is_detector_type_enabled(name, type)` is the runtime check. A detector may
detect anything, but only spans whose type is in its allowlist survive into the final replacement;
the filter runs **after `split_persons` and before merge** (keys are the final
`name`/`surname`/`patronymic`, with `person` kept as the decomposition fallback) and **applies on
every path, including explicit detector lists** (unlike `DETECTORS_ENABLED`). A forbidden type is
not replaced but is still *detected* (`spans_found` unaffected); the LLM verify pass honors it too.
Each detector defaults to its own natural emit set (a no-op — edit a set to restrict, or set a
detector's value to `None` to allow all types).

## HTTP API (`anonymizer/api.py`)

FastAPI app. `GET /health` (no auth) reports detector status; `POST /anonymize`,
`POST /anonymize/{detector}`, and `POST /reload` require an `X-API-Key` header matching the
configured key. `/anonymize` runs the full ensemble; `/anonymize/{detector}` (detector ∈ the
`DETECTORS_BY_NAME` keys) runs a single detector with **no LLM verify pass** — its `spans_found`
has just that one detector's count, for isolating each detector's contribution. `/reload` re-probes
the LMStudio model (useful if LMStudio was started after the server). Requests are serialized with
a `threading.Lock`
because the NLP models are not thread-safe (and LLM is slow anyway). The default API key is
`change-me`; the server logs a warning until a real key of 16+ chars is set via env/config. The
key check uses `secrets.compare_digest` (constant-time). Request `text` is capped at
`config.API["max_text_chars"]` (default 100 000 chars → HTTP 422 above that). Swagger/OpenAPI
endpoints (`/docs`, `/openapi.json`) are disabled. Default host is `127.0.0.1` — exposing the
service on `0.0.0.0` is only safe behind a TLS reverse proxy (it receives raw, un-anonymized PII).

## Detector evaluation tooling (`scripts_for_testing/`)

Standalone scripts for comparing detector behavior over a corpus — they live in
`scripts_for_testing/` with their `examples.json` corpus; all generated `.json`/`.html` outputs go
to `scripts_for_testing/results/`. Separate from the package, run with the venv interpreter. Two chains:

- **Per-detector matrix:** `compare_all_detectors.py` reads `examples.json` (corpus of RU texts) and
  runs each text through *each detector individually* (`anonymize_detailed(text, [module],
  verify=False)`), writing `results.json` (per example×detector: `spans_found`, `labels_in_text`,
  masked `text`). `make_compare_report.py` renders `results.json` → `report.html` (matrix
  examples×detectors). The runner calls the report generator automatically at the end, so
  `report.html` is regenerated on every run (the generator can still be run standalone).
- **LLM impact:** `compare_llm.py [N]` runs each example twice — baseline
  `[regex, natasha, presidio]` (`verify=False`) vs full 4 + LLM verify — recording spans,
  replacements and timing into `llm_impact.json`. `make_llm_report.py` renders it →
  `llm_report.html` with a "result matches" column. `[N]` limits to the first N examples (LLM
  makes up to 3 LMStudio calls per example; the full ~100-example run takes ~20+ min). As above,
  the runner invokes `make_llm_report.py` automatically after writing the JSON.

Convention: the **runners** (`compare_all_detectors.py`, `compare_llm.py`) import `anonymizer` — since they
sit in a subfolder, each prepends the repo root to `sys.path` (`parents[1]`) so the package
resolves; they eager-load models (LLM needs LMStudio up). The **report generators**
(`make_compare_report.py`, `make_llm_report.py`) are stdlib-only and must **not** import `anonymizer` —
they only read JSON, which keeps them fast and model-free. All paths are relative to each script
(`Path(__file__).parent`): the `examples.json` input stays in `scripts_for_testing/`, while
generated `.json`/`.html` outputs are written to (and read back from) `scripts_for_testing/results/`
(created automatically).

## Tests (`tests/test_anonymizer.py`, `tests/test_api.py`)

Tests live in `tests/`; a root `conftest.py` puts the project root on `sys.path` so
`import anonymizer` resolves under both `pytest` and `python -m pytest`.

- Pure-function unit tests (regex / merge / apply / `parse_entities` / `relabel_groups` /
  `collapse_repeated_labels`) run with no optional deps.
- Tests needing Natasha/Presidio are guarded with `skipif` (`needs_natasha`/`needs_presidio`) so a
  regex-only environment skips rather than fails.
- An autouse fixture disables LLM/LMStudio globally (patches `llm.LMSTUDIO_MODEL = None`) so tests
  are deterministic and make no network calls; LLM response parsing is tested separately against
  fixed JSON via `llm.parse_entities`.
- **Don't write tests that assume the *default* values of the tunable config dicts**
  (`ANONYMIZE_TYPES`, `DETECTOR_TYPES`, `DETECTORS_ENABLED`) — those are operator knobs that are
  actively edited (e.g. types pruned from a detector's `DETECTOR_TYPES` set, `ANONYMIZE_DATE` off).
  A test that needs a given type/detector enabled must set it explicitly via
  `monkeypatch.setitem(config.<DICT>, key, value)`, not rely on the shipped default.
