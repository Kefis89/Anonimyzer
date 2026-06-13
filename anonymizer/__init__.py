# -*- coding: utf-8 -*-
"""
Локальный анонимизатор персональных данных (ПДн) для короткого русскоязычного текста.

На входе строка — на выходе та же строка с заменёнными ПДн на плоские метки
(`[Имя]`, `[Телефон]`, ...). Цель — безопасно отправлять обезличенный текст во
внешние облачные LLM, не передавая туда исходные данные. Всё детектирование
локально, замена необратима.

Архитектура — ансамбль независимых детекторов (regex / Natasha / Presidio / LLM),
каждый в своём модуле в `anonymizer/detectors/`. Конвейер: детекция → разбор персон
→ слияние спанов → замена → финальная проверка через LLM.

Публичный API:
    anonymize(text) -> str                       — обезличенный текст;
    anonymize_detailed(text) -> AnonymizationResult — текст + статистика детекторов.
"""

from __future__ import annotations

from .pipeline import AnonymizationResult, anonymize, anonymize_detailed
from .span import Span

__all__ = ["anonymize", "anonymize_detailed", "AnonymizationResult", "Span"]
