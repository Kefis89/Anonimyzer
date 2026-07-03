# Third-Party Licenses / Уведомления о сторонних лицензиях

This project ("Anonimyzer", © 2026 Kefis89, MIT License — see [`LICENSE`](LICENSE))
depends on the third-party open-source packages listed below.

The MIT, BSD and Apache-2.0 licenses of these packages require that their
copyright notice and license text be preserved **when their code is
redistributed** (in source or binary form). This project declares its
dependencies in [`requirements.txt`](requirements.txt) and does **not** vendor
or bundle their code — `pip install` fetches each package separately from PyPI,
where it already ships its own license. This file is provided as good practice
and, more importantly, to satisfy the attribution obligation for any bundled
distribution of this project (e.g. a Docker image with dependencies baked in, a
PyInstaller executable, a vendored copy, or a shipped virtual environment).

The copyright lines below were copied verbatim from each package's own
`LICENSE` file as installed in the project's virtual environment.

---

## Runtime dependencies

### FastAPI — MIT License
- Copyright (c) 2018 Sebastián Ramírez
- https://github.com/fastapi/fastapi

### Pydantic — MIT License
- Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors.
- https://github.com/pydantic/pydantic

### Presidio Analyzer — MIT License
- Copyright (c) Microsoft Corporation
- https://github.com/microsoft/presidio

### Natasha — MIT License
- Copyright (c) 2016 Natasha project (Alexander Kukushkin and contributors)
- https://github.com/natasha/natasha

### spaCy — MIT License
- Copyright (C) 2016-2024 ExplosionAI GmbH, 2016 spaCy GmbH, 2015 Matthew Honnibal
- https://github.com/explosion/spaCy

### ru_core_news_lg (spaCy Russian model) — MIT License
- Copyright 2021 ExplosionAI GmbH
- https://github.com/explosion/spacy-models

### phonenumbers (python-phonenumbers) — Apache License 2.0
- Copyright David Drysdale (Python port) — a port of Google's `libphonenumber`,
  Copyright (C) The libphonenumber Authors.
- https://github.com/daviddrysdale/python-phonenumbers
- Distributed under the Apache License, Version 2.0. A copy of the license is
  available at https://www.apache.org/licenses/LICENSE-2.0
  The package ships only a `LICENSE` file (no separate `NOTICE` file), so no
  additional NOTICE text needs to be reproduced under Apache-2.0 §4(d).

### HTTPX — BSD 3-Clause License
- Copyright © 2019, Encode OSS Ltd.
- https://github.com/encode/httpx

### Uvicorn — BSD 3-Clause License
- Copyright © 2017-present, Encode OSS Ltd.
- https://github.com/encode/uvicorn

### python-dotenv — BSD 3-Clause License
- Copyright (c) 2014, Saurabh Kumar (python-dotenv); 2013, Ted Tieken
  (django-dotenv-rw); 2013, Jacob Kaplan-Moss (django-dotenv)
- https://github.com/theskumar/python-dotenv

---

## Development / testing dependencies

### pytest — MIT License
- Copyright (c) 2004 Holger Krekel and others
- https://github.com/pytest-dev/pytest

---

## Transitive dependencies

The packages above pull in a larger tree of transitive dependencies (spaCy's
`thinc`/`blis`/`cymem`/`preshed`/`murmurhash`/`srsly`/`catalogue`/`wasabi`,
Natasha's `razdel`/`yargy`/`navec`/`slovnet`/`pymorphy3`, `numpy`, `requests`,
`starlette`, `anyio`, etc.), almost all under MIT, BSD or Apache-2.0.

If you distribute a **bundle** that contains the installed dependencies, the
attribution obligation extends to that full closure. `pip-licenses` is already
available in the venv and can regenerate a complete report, including the full
license text of every installed package:

```powershell
.venv\Scripts\python.exe -m piplicenses --with-license-file --with-authors --with-urls --format=plain-vertical --output-file=THIRD_PARTY_FULL.txt
```
