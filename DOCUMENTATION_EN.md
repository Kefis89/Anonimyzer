# Anonymizer — technical documentation

🌐 [Русский](DOCUMENTATION_RU.md) · **English**

A local anonymizer of personal data (PII) for Russian-language text. The input is a string —
the output is the same string with PII replaced by flat labels (`[Имя]`, `[Телефон]`,
`[Адрес]`, …). The goal is to safely send anonymized text to external cloud LLMs without
passing the originals to them.

---

## Contents

1. [Purpose and principles](#1-purpose-and-principles)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [LM Studio + LLM setup](#4-lm-studio--llm-setup)
5. [Quick start](#5-quick-start)
6. [Use from third-party Python code](#6-use-from-third-party-python-code)
7. [HTTP API and running on a server](#7-http-api-and-running-on-a-server)
8. [Architecture and pipeline](#8-architecture-and-pipeline)
9. [Detectors](#9-detectors)
10. [Configuration](#10-configuration)
11. [Detector evaluation tooling](#11-detector-evaluation-tooling)
12. [Tests](#12-tests)
13. [Guarantees and limitations](#13-guarantees-and-limitations)
14. [Repository structure](#14-repository-structure)
15. [License and disclaimer](#15-license-and-disclaimer)

---

## 1. Purpose and principles

Anonymizer finds personal data in Russian text (full names, phone numbers, addresses,
organizations, dates, amounts, email, INN, SNILS, passports, bank cards, IP) and replaces it
with anonymized labels. The typical scenario: you have confidential text that needs to be sent
to an external cloud LLM (ChatGPT, Claude, etc.) — you first run it through Anonymizer, and only
the safe version without real data leaves your machine.

Three principles the project is built on:

- **Irreversibility.** Replacement is one-way: there is no “label → original” mapping table.
  The original data cannot be restored from the anonymized text.
- **Recall over precision.** The worst outcome is to miss PII. Over-masking (masking a non-PII
  token) is acceptable. When in doubt, the system masks.
- **Strictly local.** All detection runs on your machine. The only network call is to a **local**
  LM Studio server (`localhost:1234`), which also runs on your machine. Nothing leaves the host.

---

## 2. Requirements

| Component | Purpose | Required |
|---|---|---|
| Python 3.10+ | runtime | required |
| [Natasha](https://github.com/natasha/natasha) | NER + extraction of addresses/dates/amounts/names | recommended |
| [Presidio](https://microsoft.github.io/presidio/) + spaCy `ru_core_news_lg` | NER + RU-ID recognizers | recommended |
| LM Studio + a local LLM | semantic “fill-in” via a local LLM | optional |
| FastAPI + Uvicorn | HTTP API | optional (API only) |
| httpx | `TestClient` in the API tests | optional (tests only) |
| python-dotenv | reading `.env` | optional |

**Graceful degradation.** Any unavailable component is silently disabled, and the pipeline keeps
working on the rest. The minimal working configuration is the regex detector alone (always
available). The full one is all 4 detectors + the LLM verify pass.

OS: the project was developed on Windows (the command examples use PowerShell), but it is
cross-platform.

---

## 3. Installation

```bash
# 1. Clone the repository
git clone https://github.com/Kefis89/Anonimyzer.git
cd Anonimyzer

# 2. Create a virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# 3. Install the NLP dependencies
pip install natasha presidio-analyzer
python -m spacy download ru_core_news_lg

# 4. (optional) HTTP API and test dependencies
pip install fastapi "uvicorn[standard]" httpx python-dotenv
```

> Versions are not pinned (there is no `requirements.txt`) — the latest ones are installed.
> Natasha pulls its data (navec/slovnet) as part of the package. The spaCy model
> `ru_core_news_lg` (~0.5 GB) is downloaded by a separate command.

> ⚠️ **setuptools must stay < 81.** pymorphy2 (a Natasha dependency) discovers its dictionaries
> via `pkg_resources`, which was removed in setuptools ≥ 82 — with newer setuptools `MorphVocab()`
> crashes and the Natasha detector silently disables itself. If something upgraded setuptools,
> roll it back: `pip install "setuptools<81"`.

---

## 4. LM Studio + LLM setup

The LLM detector and the final verify pass work through **LM Studio** — a local server with an
OpenAI-compatible API. The model is not hardcoded: whatever model LM Studio has loaded is used.
Without LM Studio, the other three detectors work as usual (the LLM detector simply switches off).

1. Install [LM Studio](https://lmstudio.ai/).
2. In the model search tab, download a suitable instruct model (requirements below).
3. The **Developer / Local Server** tab → load the model and start the server on port **1234**
   (the default address is `http://localhost:1234/v1`).
4. Done. Anonymizer detects the loaded model on import via `GET /v1/models` (it takes the first
   one listed; to pin a specific model, set `LMSTUDIO["model"]` in `config.py`).

### Model requirements

The detector talks to the model over the OpenAI-compatible `/chat/completions` endpoint and is
**not tied to any particular model**. Any model that meets these requirements works:

- **Structured output (`response_format: json_schema`).** Every request sends a strict JSON schema
  with an `enum` of allowed types. The model and the LM Studio runtime must support this; otherwise
  the server returns HTTP 400, the request fails, and the LLM layer silently switches off (as if
  LM Studio were down) — the pipeline does not crash, but the fill-in and verify passes do nothing.
  (LM Studio does **not** accept `json_object`.)
- **An instruct/chat model** that follows the system prompt; output is deterministic
  (`temperature = 0`, set by the code).
- **Good Russian comprehension.** The prompts are in Russian; the model must return a `type` from
  the Russian set (enforced by the `enum`) and a **verbatim** Russian substring. If the model
  paraphrases or distorts the substring, `text.find` won’t locate it and the entity is silently
  dropped — lowering recall. The stronger the model’s Russian, the higher the recall.
- **Reasoning and plain models both work.** Reasoning models often put the JSON in
  `reasoning_content` with an empty `content`; reads fall back (`content or reasoning_content`).

### Example models that fit

Any modern instruct model in LM Studio with structured output and decent Russian. For example:

- **Qwen2.5-7B-Instruct** (or Qwen3-8B) — Qwen is what the project was tested on; strong Russian.
- **Google Gemma 2 9B Instruct** — supports structured output, decent Russian.
- **Mistral-Nemo-Instruct (12B)** — multilingual, including Russian.

A larger/stronger model usually gives higher recall (catches more of what was missed) but runs
slower. A 7–9B model is a reasonable minimum; on weaker hardware use quantized builds (GGUF Q4/Q5).

### Other notes

- If LM Studio was started **after** Anonymizer, re-probe the model: `POST /reload` (see the API)
  or restart the process.
- If the server is unavailable, the import quickly returns `connection refused`, the LLM detector
  disables itself, and the import does not hang.

---

## 5. Quick start

```powershell
# Demo on the built-in examples (prints BEFORE / AFTER / detector stats)
.venv\Scripts\python.exe -m anonymizer
```

A minimal call from Python:

```python
from anonymizer import anonymize

text = "Иванов Иван Иванович, тел. +7 916 123-45-67, ИНН 7707083893"
print(anonymize(text))
# → "[ФИО], тел. [Телефон], ИНН [ИНН]"
```

---

## 6. Use from third-party Python code

The package’s public API:

```python
from anonymizer import anonymize, anonymize_detailed, AnonymizationResult

# 1. Simple call — anonymized text only
masked: str = anonymize("текст с ПДн")

# 2. Detailed call — text + per-detector stats
res: AnonymizationResult = anonymize_detailed("текст с ПДн")
res.text          # anonymized text
res.spans_found   # dict: detector name → number of RAW hits (before merging)
                  # e.g. {"regex": 2, "natasha": 4, "presidio": 3, "llm": 1}
```

### Signature of `anonymize_detailed`

```python
anonymize_detailed(text: str, detectors=None, *, verify: bool = True) -> AnonymizationResult
```

- `detectors` — which detectors to run. By default (`None`) — all those enabled in
  `config.DETECTORS_ENABLED` (see “Which detectors to run” in section 10). An explicitly passed
  list runs as-is, without the config filter: pass a single detector to get exactly that detector’s
  contribution.
- `verify` — whether to run the final extra check via LLM (`verify_with_llm`).

Running a single detector in isolation (no network and no LLM fill-in):

```python
from anonymizer.pipeline import anonymize_detailed
from anonymizer.detectors import DETECTORS_BY_NAME

regex = DETECTORS_BY_NAME["regex"]
res = anonymize_detailed("ИНН 7707083893, e-mail a@b.com", [regex], verify=False)
# res.text == "ИНН [ИНН], e-mail [Email]"
```

### Important: model loading on import (eager loading)

`import anonymizer` is **slow and has side effects**: the Natasha/spaCy models load immediately,
and the LLM detector makes a network probe to `localhost:1234`. Therefore:

- Import the package once at your application’s startup, not on every request.
- The objects are not thread-safe — do not call `anonymize_detailed` from multiple threads in
  parallel (in the HTTP API, requests are serialized with `threading.Lock`).

### Which types to mask

The masked types are configured by constants in `anonymizer/config.py` (see
[Configuration](#10-configuration)) — globally for the whole process.

---

## 7. HTTP API and running on a server

A FastAPI app (`anonymizer/api.py`). Listens on `127.0.0.1:8077` by default (local access only).
The service accepts **un-anonymized** text, so exposing it externally (`0.0.0.0`) is only
acceptable behind a TLS reverse proxy — see “Server deployment”.

### Launch

```powershell
.venv\Scripts\python.exe run.py
```

> `run.py` is the main server entrypoint (in the project root). The equivalent command is
> `.venv\Scripts\python.exe -m anonymizer.api`.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ANONYMIZER_HOST` | listening interface | `127.0.0.1` |
| `ANONYMIZER_PORT` | port | `8077` |
| `ANONYMIZER_API_KEY` | key for the `X-API-Key` header | `change-me` |

They are read from `.env` in the project root (if `python-dotenv` is installed) or from real
environment variables. **You must set your own `ANONYMIZER_API_KEY`** — generate one like this:
`python -c "import secrets; print(secrets.token_hex(32))"`. While the default `change-me` or a key
shorter than 16 characters is in place, the server logs a warning. The `.env` file is in
`.gitignore`; a ready-made template is `.env.example` in the repository root.

### Endpoints

| Method/path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | service status and active detectors |
| `POST /anonymize` | `X-API-Key` | full ensemble (those enabled in `DETECTORS_ENABLED` + verify) |
| `POST /anonymize/{detector}` | `X-API-Key` | one detector (`regex`/`natasha`/`presidio`/`llm`), no verify |
| `POST /reload` | `X-API-Key` | re-probe the LM Studio model |

`POST /anonymize` and `/anonymize/{detector}` accept `{"text": "..."}` and return
`{"text": "...", "spans_found": {...}}`. For `/anonymize/{detector}`, `spans_found` has exactly one
key — the chosen detector’s contribution (handy for analysis). An unknown detector name → HTTP 422.
The `text` length is capped at `config.API["max_text_chars"]` (100,000 characters by default,
above which → HTTP 422): requests are processed one at a time, and a huge text would block the
service. The Swagger UI (`/docs`, `/openapi.json`) is disabled — an unnecessary attack surface for
a service handling PII.

Requests are **serialized** (`threading.Lock`): one at a time, because the NLP models are not
thread-safe (and LLM is slow anyway). The server runs with `workers=1`.

### Example calls

```bash
# Status check (locally; over the network — https://YOUR_DOMAIN via a TLS proxy)
curl http://localhost:8077/health

# Anonymization (full ensemble)
curl -X POST http://localhost:8077/anonymize \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"text":"Иванов Иван, ИНН 7707083893"}'

# A single detector only
curl -X POST http://localhost:8077/anonymize/regex \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"text":"ИНН 7707083893"}'
```

A ready-made stdlib Python client is `client_example.py` (functions `anonymize()`, `health()`).
It is configured by the environment variables `ANONYMIZER_URL` (default `http://localhost:8077`)
and `ANONYMIZER_API_KEY`. **The client does not read `.env`** — it is an example of an external
program, and only the server picks up `.env`. If the variable is not set, the client sends the
default key `change-me`, and a server with a real key responds 401:

```powershell
$env:ANONYMIZER_API_KEY = "<the same key the server uses>"
.venv\Scripts\python.exe client_example.py
```

### Server deployment

1. Clone the repository and install the dependencies (section 3), including `fastapi`/`uvicorn`.
2. Set up LM Studio + LLM (section 4) if you need the 4th detector.
3. Create a `.env` with a production `ANONYMIZER_API_KEY` (and `ANONYMIZER_PORT` if needed).
4. **TLS is mandatory for network access**: the service accepts the original (un-anonymized) text
   and the API key, which would travel over plain HTTP in clear text. Put a reverse proxy
   (nginx/caddy) with TLS in front of the service, set `ANONYMIZER_HOST=0.0.0.0` (or the address of
   an internal interface), and open only the proxy port in the firewall. Without a TLS proxy, keep
   the default `127.0.0.1` — the service will be reachable only from this machine.

> **Picking up config changes.** The server reads the config and loads the models on import. After
> editing `config.py` (for example, the type switches), **restart the process** — Uvicorn runs
> without auto-reload.

---

## 8. Architecture and pipeline

### Data model — `Span`

A detected PII fragment is described by `Span(start, stop, type, source)`: a half-open interval
`[start, stop)`, where `type` is a key from `LABELS`/`PRIORITY` and `source` is who found it.

### The full pipeline (`anonymizer/pipeline.py`, `anonymize_detailed`)

```
original text
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. DETECTION                                                │
│    Each detector in DETECTORS = [regex, natasha,            │
│    presidio, llm] returns a list of Spans. Each one's raw  │
│    hit count is written to spans_found (BEFORE merging).    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
  2. split_persons   — person span → [Имя]/[Фамилия]/[Отчество]
      │
      ▼
  3. type filter     — drop spans of types disabled in
      │                ANONYMIZE_TYPES, then drop spans whose
      │                source detector may not replace that type
      │                (DETECTOR_TYPES) — both before merge
      ▼
  4. merge_spans     — resolve overlaps by "char-painting" by
      │                PRIORITY + glue address fragments
      ▼
  5. apply_spans     — replace spans with labels (from the end
      │                of the string, trimming edge whitespace)
      ▼
  6. verify_with_llm — LLM re-reads the masked text and picks
      │                 up leftover PII (up to max_verify_passes
      │                 times); skipped when verify=False
      ▼
  7. relabel_groups  — collapse fine labels into coarse ones per
      │                 LABEL_GROUPS: [Имя]/[Фамилия]/[Отчество]
      │                 → [ФИО], [Локация] → [Адрес]
      ▼
  8. collapse_repeated_labels — collapse runs of IDENTICAL
      │                          adjacent labels: "[X] [X]" → "[X]"
      ▼
anonymized text  (+ spans_found)
```

> After grouping, the fine labels `[Имя]`/`[Фамилия]`/`[Отчество]`/`[Локация]` no longer appear in
> the final output — name components surface as `[ФИО]` and locations as `[Адрес]`. `split_persons`
> still runs internally; the grouping is the very last, presentation-only step.

### Key mechanisms

- **Merge by “char-painting” (`merge_spans`).** Each character is taken by the highest-`PRIORITY`
  type covering it; then adjacent runs of the same type are collected into spans. This resolves
  partial overlaps cleanly. Afterward, adjacent `address` fragments separated only by
  punctuation/whitespace are glued into one (AddrExtractor splits an address into `г. Уфа` /
  `ул. Ленина` / `д. 5`).
- **Replace from the end (`apply_spans`).** We go from the end of the string so offsets don’t
  shift; whitespace at the span edges is trimmed, otherwise adjacent labels fuse (`[Сумма][Дата]`).
- **Person decomposition (`split_persons`).** `NamesExtractor` is unreliable on free text (it
  confuses job titles with surnames), so it is run **only on the substring of an already-confirmed
  person span**. If decomposition fails, the span stays `[ФИО]`.
- **Eager loading.** Models load when the detector modules are imported (`natasha.NATASHA`,
  `presidio.PRESIDIO`, `llm.LMSTUDIO_MODEL` — globals). An unavailable component → global `None` →
  detector silently disabled.

---

## 9. Detectors

Four independent detectors, registered in order in `detectors/__init__.py`:
`DETECTORS = [regex, natasha, presidio, llm]`. Each is a uniform plugin: `NAME`,
`detect(text) -> list[Span]` (fault-tolerant, returns `[]` when unavailable), `available() -> bool`.
**Order matters**: at equal `PRIORITY` the first in the list “paints” characters first, so the
structural detectors come before the model-based ones.

### 9.1 regex — structured identifiers

File `detectors/regex.py`. **Always available.** Patterns are in `config.REGEXES`. Catches
deterministically: email, RU phone numbers, bank cards, SNILS, IPv4, passport, INN, monetary
amounts.

Non-obvious rules (guards against false matches — **do not “fix”**):
- **Passport requires a separator** between the series and the number, otherwise the pattern would
  match a bare 10-digit INN.
- **An amount requires a currency** (symbol/word), otherwise bare numbers (INN, postal codes) would
  become amounts.
- **Phone numbers** are caught in three forms: with a `+7`/`8` prefix; without a prefix but with
  mandatory separators; a 7-digit local number.

### 9.2 natasha — NER + rules

File `detectors/natasha.py`. NER tags PER/LOC/ORG → `person`/`loc`/`org`; plus rule-based
extractors: `AddrExtractor` → `address`, `DatesExtractor` → `date`, `MoneyExtractor` → `money`.
`NamesExtractor` is used separately — in `split_persons` for decomposing full names.

### 9.3 presidio — spaCy + RU-ID recognizers

File `detectors/presidio.py`. NER on spaCy `ru_core_news_lg` + custom pattern recognizers
`RU_INN` / `RU_SNILS` / `RU_PASSPORT` + the built-in CreditCard/Ip, explicitly registered for `ru`.

> **`PhoneRecognizer` is removed from the registry.** The `phonenumbers` library greedily accepts
> bare digit groups (INN/passport) as a phone, and phone outranks INN → you’d get `[Телефон]` where
> `[ИНН]` belongs. RU phone numbers are reliably caught by the regex detector.

> **`EmailRecognizer` is not registered.** Its `validate_result` calls `tldextract`, which on a
> cold cache makes an HTTPS request to the internet for the public suffix list — that breaks the
> “strictly local” principle (and without internet it hangs on a timeout). Email is reliably caught
> by the regex detector at the same priority 100.

### 9.4 llm — semantic fill-in via an LLM

File `detectors/llm.py`. A local LLM via LM Studio. Its role is **contextual fill-in of
semantic entities** (names, organizations, locations, addresses, dates, amounts) that the formal
detectors missed.

**How it works (important for understanding the guarantees):**
- LLM **does not return** a ready string or coordinates — it returns a list of
  `{"type": "...", "text": "<verbatim substring>"}`.
- Anonymizer builds the spans itself: it searches for the verbatim substring in the original
  (`text.find`) and marks all of its occurrences. If the model “invents” a substring that is not in
  the text — it is simply **not found and discarded**. LLM **cannot** change, insert, or delete
  characters in the source text (see [section 13](#13-guarantees-and-limitations)).
- **LLM does not return structured IDs** (`config.LLM_SKIP_TYPES`: email/phone/card/ip/
  passport/snils/inn) — it often errs on them (confuses SNILS with a phone, INN with a passport),
  and regex/Presidio own them.
- **Verify pass** (`verify_with_llm`): LLM re-reads the already-masked text, ignoring the `[...]`
  labels, and looks for leftover PII — up to `max_verify_passes` times.

### Priorities on conflict (`config.PRIORITY`)

The larger the number, the more important the label on an overlap:

| Priority | Types |
|---:|---|
| 100 | email, phone, card, ip, passport, snils |
| 95 | inn |
| 90 | surname, name, patronymic |
| 80 | address |
| 70 | person |
| 60 | money |
| 50 | org |
| 40 | loc |
| 30 | date |

### Labels (`config.LABELS`)

`name`→`[Имя]`, `surname`→`[Фамилия]`, `patronymic`→`[Отчество]`, `person`→`[ФИО]`,
`org`→`[Организация]`, `loc`→`[Локация]`, `address`→`[Адрес]`, `email`→`[Email]`,
`phone`→`[Телефон]`, `inn`→`[ИНН]`, `snils`→`[СНИЛС]`, `passport`→`[Паспорт]`,
`card`→`[БанковскаяКарта]`, `ip`→`[IP]`, `date`→`[Дата]`, `money`→`[Сумма]`.
(The label values are Russian — that is exactly what the tool emits into the Russian text.)

---

## 10. Configuration

Everything tunable is collected in `anonymizer/config.py`, separate from the logic.

| Object | What it sets |
|---|---|
| `LABELS` | type → label text |
| `PRIORITY` | who wins on an overlap |
| `REGEXES` | structured-ID patterns (the `_MONEY_*` blocks compose the amount pattern) |
| `LMSTUDIO` | `base_url`, `model` (None = auto-detect), `timeout`, `temperature`, `max_tokens`, `max_verify_passes` |
| `LLM_SKIP_TYPES` | which types NOT to take from LLM’s answer |
| `LABEL_GROUPS` | final grouping of fine labels into coarse ones (components → `[ФИО]`, loc → `[Адрес]`) |
| `ANONYMIZE_*` / `ANONYMIZE_TYPES` | which types to mask |
| `DETECTOR_*` / `DETECTORS_ENABLED` | which detectors to run |
| `DETECTOR_*_TYPES` / `DETECTOR_TYPES` | which types each detector may replace |
| `API` | host / port / api_key (overridable via env) / max_text_chars |

### Which types to anonymize

Each span type has a boolean constant (`True` by default for all except `money` and `date` — amounts
and dates are intentionally left unmasked):

```python
ANONYMIZE_NAME = True
ANONYMIZE_EMAIL = True
ANONYMIZE_DATE = False    # dates are NOT masked (project default)
ANONYMIZE_MONEY = False   # amounts are NOT masked (project default)
...
```

They are collected into the `ANONYMIZE_TYPES` dict, and the pipeline checks `is_type_enabled(type)`
and **drops spans of disabled types before merging** — both in the main pass and in
`verify_with_llm`.

Behavior:
- A disabled type is **not masked**, but is **still detected** (`spans_found` does not change — it
  is detection statistics, not masking).
- Full-name components are controlled separately: you can disable `name` while keeping
  `surname`/`patronymic` (the filter runs after person decomposition).
- For the HTTP API, config edits are picked up only after a process restart.

### Final label grouping (`LABEL_GROUPS`)

The very last pipeline step rewrites fine labels into coarse groups, then collapses adjacent
duplicates. `LABEL_GROUPS` maps a fine type to the type whose label replaces it:

```python
LABEL_GROUPS = {
    "name": "person", "surname": "person", "patronymic": "person",  # → [ФИО]
    "loc": "address",                                               # → [Адрес]
}
```

Behavior:
- Name components → `[ФИО]`; locations → `[Адрес]`. After grouping,
  `collapse_repeated_labels` merges any resulting run of identical adjacent labels separated by
  whitespace only (not punctuation): `[ФИО] [ФИО]` → `[ФИО]`, but `[ФИО], [ФИО]` stays two people.
- This is presentation-only and runs after `verify_with_llm`, so it also normalizes labels the
  verify pass added. It does **not** change detection or merge priorities.
- Set `LABEL_GROUPS = {}` to disable grouping (fine labels then appear verbatim).

### Which detectors to run

Like the types, each detector has a boolean constant (`True` by default for all):

```python
DETECTOR_REGEX = True
DETECTOR_NATASHA = True
DETECTOR_PRESIDIO = True
DETECTOR_LLM = True
```

They are collected into the `DETECTORS_ENABLED` dict; the check is `is_detector_enabled(name)`.

Behavior:
- A disabled detector is **not run** in the default set (`anonymize(text)`, `POST /anonymize`) and
  **does not appear in `spans_found`**.
- The filter applies only to runs without an explicit list: `anonymize_detailed(text, [module])`,
  `POST /anonymize/{detector}`, and the eval scripts run the passed detector regardless (diagnostics
  and detector evaluation keep working).
- `DETECTOR_LLM = False` additionally disables the final LLM verify pass (`verify_with_llm`) —
  i.e. LLM is not called at all.
- Disabling a detector **does not cancel loading its models on import** (eager loading); it only
  removes its participation in the pipeline.
- Like the rest of the config, it is picked up after a process restart.

### Which types each detector may replace

A finer knob than the on/off switch above: each detector may **find** anything, but only the span
types listed for its source make it into the **final replacement**. Use it when testing shows one
detector is more reliable for a type than another, or a detector false-positives on some type and
pollutes the output — you can stop it replacing that type without disabling the whole detector.

```python
DETECTOR_REGEX_TYPES = {"email", "phone", "card", "snils", "ip", "passport", "inn", "money"}
DETECTOR_NATASHA_TYPES = {"name", "surname", "patronymic", "person", "org", "loc", "address", "date", "money"}
DETECTOR_PRESIDIO_TYPES = {"name", "surname", "patronymic", "person", "org", "loc", "card", "ip", "date", "inn", "snils", "passport"}
DETECTOR_LLM_TYPES = {"name", "surname", "patronymic", "person", "org", "loc", "address", "date", "money"}
```

They are collected into the `DETECTOR_TYPES` dict; the check is `is_detector_type_enabled(name, type)`.

Behavior:
- **Defaults are each detector's natural emit set** — a no-op until you edit it. To forbid a type
  for a detector, remove it from that detector's set; setting a detector's value to `None` allows
  all types.
- The filter runs **after person decomposition and before merge**, so the keys are the final types
  (`name`/`surname`/`patronymic` rather than `person`; `person` is kept as the fallback when
  decomposition fails) and spans still carry their originating detector (`Span.source`).
- It applies **everywhere** — including the explicit single-detector paths
  (`anonymize_detailed(text, [module])`, `POST /anonymize/{detector}`, the eval scripts). The
  masked text always reflects the policy (unlike `DETECTORS_ENABLED`, which an explicit list
  bypasses).
- A forbidden type is **not replaced**, but is **still detected** (`spans_found` does not change).
- The LLM verify pass honors it too (only `llm`'s allowed types are picked up).

---

## 11. Detector evaluation tooling

Standalone scripts in the `scripts_for_testing/` folder for comparing detector behavior over a
corpus. The corpus `examples.json` lives there too, and all generated `.json`/`.html` results go to
the `scripts_for_testing/results/` subfolder (created automatically). They are run with the venv
interpreter. Two chains:

> **All examples in `examples.json` and `examples_en.json` are AI-generated** — they are fictional
> texts containing no real personal data; any resemblance to real people, addresses, or identifiers
> is coincidental.

**The “example × detector” matrix:**
```powershell
.venv\Scripts\python.exe scripts_for_testing\compare_all_detectors.py   # examples.json → results.json
.venv\Scripts\python.exe scripts_for_testing\make_compare_report.py   # results.json → report.html
```
`compare_all_detectors.py` runs each example from `examples.json` through each detector individually
(`anonymize_detailed(text, [module], verify=False)`) and writes `results.json` (for each pair:
`spans_found`, `labels_in_text`, the anonymized `text`). `make_compare_report.py` builds a
self-contained HTML table from it. On completion, `compare_all_detectors.py` calls
`make_compare_report.py` itself, so `report.html` is regenerated automatically — the separate
command above is only for rebuilding the report without re-running the corpus.

**Evaluating LLM’s contribution (the slowest detector):**
```powershell
.venv\Scripts\python.exe scripts_for_testing\compare_llm.py [N]    # examples.json → llm_impact.json
.venv\Scripts\python.exe scripts_for_testing\make_llm_report.py    # llm_impact.json → llm_report.html
```
`compare_llm.py` runs each example in two configurations — baseline `[regex, natasha, presidio]`
(no LLM, `verify=False`) vs. all 4 + verify — recording the span count, the replacement count, the
**time**, and whether the resulting texts match. The optional `[N]` limits the number of examples
(LLM makes up to 3 LM Studio calls per example; a full ~100-example run takes 20+ minutes).
`make_llm_report.py` builds a comparison table with a “result matches” column. On completion,
`compare_llm.py` calls `make_llm_report.py` itself, so `llm_report.html` is regenerated
automatically — the separate command above is only for rebuilding the report without re-running.

> Convention: the **runners** (`compare_all_detectors.py`, `compare_llm.py`) import `anonymizer` —
> they live in a subfolder, so they prepend the project root to `sys.path` (`parents[1]`); they
> load the models, and LLM needs LM Studio. The **report generators** (`make_compare_report.py`,
> `make_llm_report.py`) are stdlib-only and **do not import** `anonymizer` (they read JSON → fast,
> with no model loading). All paths are taken relative to the script (`Path(__file__).parent`): the
> `examples.json` input stays in `scripts_for_testing/`, and the generated `.json`/`.html` go to
> `scripts_for_testing/results/`.

---

## 12. Tests

The tests live in `tests/`; the root `conftest.py` adds the project root to `sys.path` so that
`import anonymizer` works under both `pytest` and `python -m pytest` from any directory.

```powershell
# The whole suite
.venv\Scripts\python.exe -m pytest -v

# A single file / class / case
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py -v
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py::TestAnonymizeTypeConfig -v
.venv\Scripts\python.exe -m pytest tests/test_anonymizer.py::TestRegexStructuredIDs::test_email -v
```

- Pure-function unit tests (regex / merge / apply / `parse_entities` / collapsing / type and
  detector switches) work without the optional dependencies.
- Tests that need Natasha/Presidio are marked with `skipif` (`needs_natasha`/`needs_presidio`) — in
  a regex-only environment they are skipped rather than failing.
- An autouse fixture globally disables LLM/LM Studio (`llm.LMSTUDIO_MODEL = None`) → the tests are
  deterministic and make no network calls; LLM response parsing is tested separately against fixed
  JSON.

---

## 13. Guarantees and limitations

- **Irreversibility.** There is no mapping table; the originals cannot be restored from the
  anonymized text.
- **Recall over precision.** Over-masking (covering a non-PII token) is possible — a deliberate
  trade-off in favor of not missing data. In particular, LLM may return an extra/frequent
  substring, in which case all of its occurrences are masked.
- **LLM does not distort the source text.** The model does not produce the output string — it only
  names what to mask, as a verbatim quote. The replacement is done by deterministic code on the
  original. A “hallucinated” substring that is not in the text is harmless — it is not found and is
  discarded.
- **Not thread-safe.** The NLP models are not designed for parallel calls; the HTTP API serializes
  requests with `threading.Lock`. To scale, use several instances behind a load balancer.
- **Local only.** The only external call is to the local LM Studio. If it is off, LLM silently
  disables itself and the other detectors keep working.
- **Detection quality** depends on the models (Natasha/spaCy/LLM) and the regex patterns — this is
  not a legally certified anonymization tool, but an engineering filter.

---

## 14. Repository structure

```
anonymizer/                 the package
├── __init__.py             public API: anonymize, anonymize_detailed
├── __main__.py             demo (python -m anonymizer)
├── config.py               ALL settings (labels, priorities, regex, LMStudio, types, detectors, API)
├── span.py                 the Span model
├── pipeline.py             the anonymize_detailed orchestrator
├── merge.py                merge_spans / apply_spans / relabel_groups / collapse_repeated_labels
├── persons.py              split_persons (full-name decomposition)
├── api.py                  the FastAPI app
└── detectors/
    ├── __init__.py         DETECTORS, DETECTORS_BY_NAME
    ├── regex.py            detector 1: structured IDs
    ├── natasha.py          detector 2: NER + rules
    ├── presidio.py         detector 3: spaCy + RU-ID
    └── llm.py             detector 4: LLM + verify_with_llm

conftest.py                 root conftest (puts the project root on sys.path for tests/)
tests/                      tests
├── test_anonymizer.py      unit tests for the pipeline and detectors
└── test_api.py             HTTP API tests
run.py                      run the HTTP server (main entrypoint)
client_example.py           API client example (stdlib)

scripts_for_testing/        detector comparison tooling (see section 11)
├── examples.json           corpus of test texts
├── compare_all_detectors.py  run over each detector → results.json
├── make_compare_report.py  results.json → report.html
├── compare_llm.py         compare 3 detectors vs 4 + verify → llm_impact.json
├── make_llm_report.py     llm_impact.json → llm_report.html
└── results/                generated results and reports (*.json, *.html)

README.md                   short project description (the GitHub landing page)
CLAUDE.md                   instructions for Claude Code
DOCUMENTATION_RU.md         documentation in Russian
DOCUMENTATION_EN.md         this file (documentation in English)
LICENSE                     the MIT license
THIRD_PARTY_LICENSES.md     third-party attribution (MIT/BSD/Apache-2.0)
.env.example                .env template (ANONYMIZER_API_KEY / HOST / PORT)
.gitignore                  git exclusions (.venv, .env, .claude, results/, etc.)
```

---

## 15. License and disclaimer

### Free license

The project is distributed as **free, open-source software** — it may be freely used, copied,
modified, and distributed. The full terms are in the [`LICENSE`](LICENSE) file in the repository
root (the **MIT** license).

The project uses third-party open-source libraries under the MIT, BSD, and Apache-2.0 licenses
(FastAPI, Pydantic, Presidio, Natasha, spaCy, phonenumbers, and others). Their copyright holders
and terms are listed in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md); those licenses require
preserving the copyright notice when copies of their code are redistributed (for example, as part of
a bundled distribution).

### Disclaimer

> ⚠️ **THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.**

The software is distributed **free of charge**; by installing, running, or otherwise using it, the
user agrees to the following terms:

- **To the maximum extent permitted by applicable law**, the author and copyright holders **bear no
  liability** for any consequences of using or being unable to use the project, including any
  direct, indirect, incidental, or consequential damages, lost profits, leakage or disclosure of
  personal data missed during anonymization, or any detection errors.
- Anonymizer is an engineering filter, **not a certified information-security tool**. It does not
  guarantee the detection and removal of 100% of personal data (see
  [Guarantees and limitations](#13-guarantees-and-limitations)): quality depends on the models and
  patterns, and both misses and over-masking are possible. The project is **not intended** for
  applications where missing PII leads to a threat to life, health, or other critical consequences.
- **All responsibility for the result lies with the user.** Before sending anonymized text to
  external services, review the output. The user is solely responsible for the lawfulness of
  processing personal data and for compliance with applicable law (for example, Russian Federal Law
  No. 152-FZ “On Personal Data”, the GDPR, and other regulations). The decision on the program’s
  suitability for a particular task is made by the user independently and at their own risk.

If you do not agree to these terms — do not use the project. The legally binding text is the MIT
license terms in the [`LICENSE`](LICENSE) file; this section is an explanation of it.
