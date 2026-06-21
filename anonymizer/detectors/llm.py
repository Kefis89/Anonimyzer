# -*- coding: utf-8 -*-
"""
Детектор 4: локальная LLM через LMStudio — контекстный «добор» смысловых
сущностей и финальная проверка уже закрашенного текста.

Модель не зашита: при импорте берётся та, что загружена в LMStudio (см.
_detect_model). Требования к модели — в DOCUMENTATION (раздел про LM Studio):
OpenAI-совместимый chat-эндпоинт, поддержка structured output
(response_format: json_schema) и достаточное понимание русского.

LMStudio вызывается через stdlib urllib (без дополнительных пакетов).
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import List, Optional

from ..config import (
    LMSTUDIO, LLM_SKIP_TYPES, is_detector_enabled, is_detector_type_enabled,
    is_type_enabled, log,
)
from ..merge import apply_spans, merge_spans
from ..span import Span

NAME = "llm"

# Маппинг русских типов из ответа модели в наши ключи LABELS.
LLM_TYPE_MAP = {
    "имя": "name", "фамилия": "surname", "отчество": "patronymic",
    "фио": "person", "лицо": "person", "персона": "person",
    "организация": "org", "компания": "org",
    "локация": "loc", "город": "loc", "страна": "loc", "регион": "loc",
    "адрес": "address",
    "email": "email", "почта": "email",
    "телефон": "phone", "инн": "inn", "снилс": "snils",
    "паспорт": "passport", "карта": "card", "ip": "ip",
    "дата": "date", "сумма": "money",
}

# Канонический набор допустимых значений type (из него строим и текст промпта,
# и enum JSON-схемы, чтобы модель возвращала только наши метки).
_LLM_TYPES = [
    "имя", "фамилия", "отчество", "организация", "локация", "адрес", "email",
    "телефон", "инн", "снилс", "паспорт", "карта", "ip", "дата", "сумма",
]
_LLM_TYPE_LIST = ", ".join(_LLM_TYPES)

# JSON-схема ответа. Этот LMStudio принимает response_format только типа
# 'json_schema' или 'text' (но НЕ 'json_object'). Жёсткая схема с enum гарантирует
# валидный JSON и тип строго из нашего набора (иначе модель отдаёт английские
# имена типа "phone_number", которые не на что мапить).
LMSTUDIO_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "pii_entities",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": _LLM_TYPES},
                            "text": {"type": "string"},
                        },
                        "required": ["type", "text"],
                    },
                }
            },
            "required": ["entities"],
        },
    },
}

LLM_DETECT_SYSTEM = (
    "Ты — локальная система обезличивания персональных данных в русском тексте. "
    "Найди в тексте пользователя ВСЕ персональные данные. Для каждой сущности верни "
    "её тип и ДОСЛОВНУЮ подстроку из текста — точно тот же регистр и падеж, как в "
    "оригинале (иначе подстроку нельзя будет найти и заменить). "
    f"Допустимые значения type: {_LLM_TYPE_LIST}. "
    "Имя, фамилию и отчество возвращай ОТДЕЛЬНЫМИ сущностями. "
    "Сосредоточься на смысловых сущностях (имена, организации, локации, адреса, "
    "даты, суммы). Структурированные идентификаторы — телефон, email, ИНН, СНИЛС, "
    "паспорт, банковскую карту, IP — НЕ возвращай: их обрабатывает отдельный модуль. "
    'Ответ — СТРОГО JSON вида {"entities":[{"type":"...","text":"..."}]}. '
    "Без пояснений, без markdown, без любого текста вне JSON. "
    'Если ничего не найдено — {"entities":[]}.'
)

LLM_VERIFY_SYSTEM = (
    "Текст уже частично обезличен: настоящие данные заменены на заглушки в "
    "квадратных скобках, например [Имя], [Телефон], [Адрес]. "
    "Найди ОСТАВШИЕСЯ персональные данные, которые ещё НЕ закрыты заглушками. "
    "Сами заглушки вида [...] полностью игнорируй — это не данные. "
    "Для каждой найденной сущности верни тип и ДОСЛОВНУЮ подстроку из текста. "
    "Ищи смысловые сущности (имена, организации, локации, адреса, даты, суммы); "
    "структурированные идентификаторы (телефон, email, ИНН, СНИЛС, паспорт, карту, "
    "IP) НЕ возвращай. "
    f"Допустимые значения type: {_LLM_TYPE_LIST}. "
    'Ответ — СТРОГО JSON {"entities":[{"type":"...","text":"..."}]}, без пояснений '
    'и markdown. Если всё уже обезличено — {"entities":[]}.'
)

# Имя загруженной модели определяем СРАЗУ при импорте (не лениво). None — если
# сервис недоступен; на localhost недоступный сервер отвечает «connection refused»
# мгновенно, так что импорт не зависает.
def _detect_model() -> Optional[str]:
    try:
        url = LMSTUDIO["base_url"].rstrip("/") + "/models"
        with urllib.request.urlopen(url, timeout=LMSTUDIO["timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data", [])
        if models:
            return LMSTUDIO["model"] or models[0]["id"]
    except Exception as e:
        log.warning("LMStudio недоступен, LLM-детектор пропущен: %s", e)
    return None


# Пробуется заранее, при импорте модуля.
LMSTUDIO_MODEL = _detect_model()


def reprobe() -> Optional[str]:
    """Заново определить модель LMStudio (если сервис подняли после старта)."""
    global LMSTUDIO_MODEL
    LMSTUDIO_MODEL = _detect_model()
    return LMSTUDIO_MODEL


def available() -> bool:
    return LMSTUDIO_MODEL is not None


def _lmstudio_chat(system_prompt: str, user_text: str) -> Optional[str]:
    """Один запрос к /chat/completions. Возвращает content или None при ошибке."""
    model = LMSTUDIO_MODEL
    if not model:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": LMSTUDIO["temperature"],
        "max_tokens": LMSTUDIO["max_tokens"],
        "response_format": LMSTUDIO_JSON_SCHEMA,
    }
    try:
        url = LMSTUDIO["base_url"].rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=LMSTUDIO["timeout"]) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        msg = result["choices"][0]["message"]
        # У reasoning-моделей при схемном ответе JSON приходит в reasoning_content,
        # а content пустой — поэтому берём с запасным вариантом.
        return msg.get("content") or msg.get("reasoning_content") or None
    except Exception as e:
        log.warning("LMStudio: ошибка запроса: %s", e)
        return None


def parse_entities(content: str, text: str) -> List[Span]:
    """Из JSON-ответа модели достаём спаны: ищем КАЖДОЕ дословное вхождение text."""
    spans: List[Span] = []
    try:
        data = json.loads(content)
    except Exception:
        log.warning("Модель вернула не-JSON, ответ проигнорирован")
        return spans
    for ent in data.get("entities", []):
        etype = LLM_TYPE_MAP.get(str(ent.get("type", "")).strip().lower())
        sub = ent.get("text", "")
        # Структурированные ID игнорируем — это зона regex/Presidio (см. LLM_SKIP_TYPES).
        if not etype or not sub or etype in LLM_SKIP_TYPES:
            continue
        start = 0
        while True:
            idx = text.find(sub, start)
            if idx == -1:
                break
            spans.append(Span(idx, idx + len(sub), etype, NAME))
            start = idx + 1  # +1, чтобы ловить и пересекающиеся вхождения
    return spans


def detect(text: str) -> List[Span]:
    content = _lmstudio_chat(LLM_DETECT_SYSTEM, text)
    if content is None:
        return []
    return parse_entities(content, text)


# --- Финальная проверка уже закрашенного текста ----------------------------

_PLACEHOLDER = re.compile(r"\[[^\]]+\]")


def _inside_placeholder(text: str, sp: Span) -> bool:
    """True, если спан пересекается с уже расставленной заглушкой [...]."""
    for m in _PLACEHOLDER.finditer(text):
        if sp.start < m.end() and m.start() < sp.stop:
            return True
    return False


def verify_with_llm(masked: str, max_passes: int = 2) -> str:
    """
    Отдаём уже закрашенный текст модели с просьбой найти оставшиеся ПДн (заглушки
    [...] игнорируются), закрашиваем найденное, повторяем до max_passes раз.
    """
    # DETECTOR_LLM=False означает «не дёргать LLM вообще» — гасим и verify.
    if LMSTUDIO_MODEL is None or not is_detector_enabled(NAME):
        return masked
    for _ in range(max_passes):
        content = _lmstudio_chat(LLM_VERIFY_SYSTEM, masked)
        if content is None:
            break
        spans = parse_entities(content, masked)
        spans = [s for s in spans if not _inside_placeholder(masked, s)]
        spans = [s for s in spans if is_type_enabled(s.type)]  # уважаем конфиг типов
        spans = [s for s in spans if is_detector_type_enabled(NAME, s.type)]  # и пер-детекторный набор
        if not spans:
            break
        spans = merge_spans(masked, spans)
        masked = apply_spans(masked, spans)
    return masked
