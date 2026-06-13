# -*- coding: utf-8 -*-
"""
Детектор 3: Presidio — NER на spaCy ru + кастомные распознаватели РФ-ID.

AnalyzerEngine создаётся СРАЗУ при импорте модуля (не лениво). Если presidio или
модель spaCy недоступны — детектор молча отключается (PRESIDIO = None).
"""

from __future__ import annotations

from typing import List

from ..config import log
from ..span import Span

NAME = "presidio"


def _load():
    """Создаёт AnalyzerEngine. None — если presidio/модель недоступны."""
    try:
        from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_analyzer.predefined_recognizers import (
            CreditCardRecognizer, IpRecognizer,
        )

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "ru", "model_name": "ru_core_news_lg"}],
        })
        nlp_engine = provider.create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["ru"])

        # Кастомные шаблонные распознаватели под РФ-идентификаторы.
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="RU_INN", supported_language="ru",
            patterns=[Pattern("inn", r"\b\d{10}\b|\b\d{12}\b", 0.4)]))
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="RU_SNILS", supported_language="ru",
            patterns=[Pattern("snils", r"\b\d{3}-\d{3}-\d{3}[\s-]\d{2}\b", 0.6)]))
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="RU_PASSPORT", supported_language="ru",
            patterns=[Pattern("passport", r"\b\d{2}\s\d{2}\s\d{6}\b|\b\d{4}\s\d{6}\b", 0.6)]))

        # Некоторые встроенные распознаватели (card/ip) по умолчанию заточены
        # под "en" и для ru не активны — регистрируем их явно для "ru".
        # ВАЖНО: EmailRecognizer НЕ регистрируем — его validate_result зовёт
        # tldextract, который при пустом кэше идёт в интернет за public suffix
        # list, нарушая принцип «строго локально». Email и так надёжно ловит
        # regex-детектор с тем же приоритетом 100.
        for cls in (CreditCardRecognizer, IpRecognizer):
            try:
                analyzer.registry.add_recognizer(cls(supported_language="ru"))
            except Exception as e:
                log.warning("Presidio: распознаватель %s пропущен: %s", cls.__name__, e)

        # AnalyzerEngine со списком языков САМ грузит в реестр предопределённые
        # распознаватели, включая PhoneRecognizer для ru. phonenumbers «жадно»
        # принимает голые группы цифр (ИНН/паспорт) за телефон, а телефон важнее ИНН
        # по приоритету → получался [Телефон] на месте [ИНН]. Поэтому выбрасываем его
        # из реестра; РФ-телефоны (+7/8) надёжно ловит regex-детектор.
        analyzer.registry.recognizers = [
            r for r in analyzer.registry.recognizers if r.name != "PhoneRecognizer"
        ]
        return analyzer
    except Exception as e:  # не установлен presidio / не скачана модель spaCy
        log.warning("Presidio недоступен, детектор пропущен: %s", e)
        return None


# Загружается заранее, при импорте модуля.
PRESIDIO = _load()


def available() -> bool:
    return PRESIDIO is not None


# Типы сущностей Presidio → наши ключи.
_PRESIDIO_MAP = {
    "PERSON": "person", "NRP": "person",
    "LOCATION": "loc", "GPE": "loc",
    "ORGANIZATION": "org", "ORG": "org",
    "EMAIL_ADDRESS": "email", "PHONE_NUMBER": "phone",
    "CREDIT_CARD": "card", "IP_ADDRESS": "ip", "DATE_TIME": "date",
    "RU_INN": "inn", "RU_SNILS": "snils", "RU_PASSPORT": "passport",
}


def detect(text: str) -> List[Span]:
    if PRESIDIO is None:
        return []
    spans: List[Span] = []
    try:
        for r in PRESIDIO.analyze(text=text, language="ru"):
            etype = _PRESIDIO_MAP.get(r.entity_type)
            if etype:
                spans.append(Span(r.start, r.end, etype, NAME))
    except Exception as e:
        log.warning("Presidio: ошибка анализа: %s", e)
    return spans
