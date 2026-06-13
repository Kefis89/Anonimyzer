# -*- coding: utf-8 -*-
"""
Реестр детекторов. Каждый модуль-детектор предоставляет:
  NAME: str                       — короткое имя ('regex'/'natasha'/'presidio'/'llm');
  detect(text) -> list[Span]      — отказоустойчив: при недоступности возвращает [];
  available() -> bool             — доступен ли детектор в текущей среде.

Порядок важен: regex и структурные детекторы идут раньше, чтобы при равном
приоритете «закрашивать» первыми (см. merge_spans).
"""

from __future__ import annotations

from . import llm, natasha, presidio, regex

DETECTORS = [regex, natasha, presidio, llm]

# Для выборочного запуска одного детектора по имени (см. /anonymize/{detector}).
DETECTORS_BY_NAME = {m.NAME: m for m in DETECTORS}
