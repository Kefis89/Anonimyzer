# -*- coding: utf-8 -*-
"""
HTTP-API анонимайзера на FastAPI.

Запуск:  python -m anonymizer.api   (слушает 127.0.0.1:8077 по умолчанию)

Переменные окружения (переопределяют config.API):
    ANONYMIZER_HOST, ANONYMIZER_PORT, ANONYMIZER_API_KEY

Эндпоинты:
    GET  /health     — статус сервиса и активные детекторы (без ключа);
    POST /anonymize  — обезличивание текста (нужен заголовок X-API-Key);
    POST /anonymize/{detector} — прогон одним детектором, без LLM-verify (X-API-Key);
    POST /reload     — пере-определить модель LMStudio (нужен X-API-Key).
"""

from __future__ import annotations

import os
import secrets
import threading
from enum import Enum
from typing import Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import API, log
from .detectors import DETECTORS_BY_NAME, llm, natasha, presidio
from .pipeline import anonymize_detailed

# Подхватываем переменные из .env в корне проекта (если установлен python-dotenv
# и файл существует). Без python-dotenv просто используются реальные переменные
# окружения — это не обязательная зависимость.
try:
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

# --- конфиг с переопределением через окружение ------------------------------
HOST = os.environ.get("ANONYMIZER_HOST", API["host"])
PORT = int(os.environ.get("ANONYMIZER_PORT", API["port"]))
API_KEY = os.environ.get("ANONYMIZER_API_KEY", API["api_key"])

if API_KEY == "change-me" or len(API_KEY) < 16:
    log.warning("API-ключ не задан или слишком короткий (<16 символов). Сгенерируйте "
                "надёжный (python -c \"import secrets; print(secrets.token_hex(32))\") "
                "и задайте через ANONYMIZER_API_KEY или config.API['api_key'].")

# Пайплайн (Natasha/spaCy) не потокобезопасен — сериализуем обработку запросов.
_LOCK = threading.Lock()

# Swagger/OpenAPI отключены: сервис держит ПДн, лишняя поверхность ни к чему.
# Для отладки верните дефолты, убрав три аргумента *_url.
app = FastAPI(title="Anonymizer API", version="1.0",
              docs_url=None, redoc_url=None, openapi_url=None)


# --- модели запроса/ответа --------------------------------------------------
class AnonymizeRequest(BaseModel):
    # Лимит длины — защита от DoS: запросы сериализуются _LOCK, гигантский текст
    # занял бы NLP-модели (и квадратичный бэктрекинг регэкспов) на минуты.
    text: str = Field(max_length=API["max_text_chars"])


class AnonymizeResponse(BaseModel):
    text: str
    spans_found: Dict[str, int]


# Допустимые имена детекторов для /anonymize/{detector}. Строим из реестра детекторов,
# чтобы список не дублировать; FastAPI валидирует path-параметр (неизвестное → 422).
DetectorName = Enum("DetectorName", {n: n for n in DETECTORS_BY_NAME}, type=str)


# --- авторизация ------------------------------------------------------------
def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    # compare_digest — сравнение за константное время (защита от timing-атаки);
    # кодируем в байты: строковый вариант не принимает не-ASCII.
    if x_api_key is None or not secrets.compare_digest(
            x_api_key.encode("utf-8"), API_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="неверный или отсутствующий X-API-Key")


def _detectors_status() -> dict:
    return {
        "natasha": natasha.available(),
        "presidio": presidio.available(),
        "llm": llm.LMSTUDIO_MODEL,   # имя модели или null
    }


# --- эндпоинты --------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "detectors": _detectors_status()}


@app.post("/anonymize", response_model=AnonymizeResponse,
          dependencies=[Depends(require_api_key)])
def anonymize_endpoint(req: AnonymizeRequest) -> AnonymizeResponse:
    # Один запрос за раз: модели не потокобезопасны, а LLM и так медленный.
    with _LOCK:
        result = anonymize_detailed(req.text)
    return AnonymizeResponse(text=result.text, spans_found=result.spans_found)


@app.post("/anonymize/{detector}", response_model=AnonymizeResponse,
          dependencies=[Depends(require_api_key)])
def anonymize_one_endpoint(detector: DetectorName, req: AnonymizeRequest) -> AnonymizeResponse:
    """Прогон одним выбранным детектором (без LLM-verify) — чистый вклад детектора."""
    module = DETECTORS_BY_NAME[detector.value]
    with _LOCK:
        result = anonymize_detailed(req.text, [module], verify=False)
    return AnonymizeResponse(text=result.text, spans_found=result.spans_found)


@app.post("/reload", dependencies=[Depends(require_api_key)])
def reload_llm() -> dict:
    """Пере-определить модель LMStudio (если её подняли уже после старта сервера)."""
    llm.reprobe()
    return {"status": "reloaded", "detectors": _detectors_status()}


def serve() -> None:
    import uvicorn
    log.info("Anonymizer API слушает http://%s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, workers=1)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    serve()
