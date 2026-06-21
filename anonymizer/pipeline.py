# -*- coding: utf-8 -*-
"""Оркестратор конвейера обезличивания + результат со статистикой детекторов."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import (
    LMSTUDIO, is_detector_enabled, is_detector_type_enabled, is_type_enabled, log,
)
from .detectors import DETECTORS
from .detectors.llm import verify_with_llm
from .merge import apply_spans, collapse_repeated_labels, merge_spans, relabel_groups
from .persons import split_persons
from .span import Span


@dataclass
class AnonymizationResult:
    """Результат обезличивания одной строки."""
    text: str                                   # обезличенный текст
    spans_found: Dict[str, int] = field(default_factory=dict)  # детектор → число сырых спанов (ДО слияния)


def anonymize_detailed(text: str, detectors: Optional[Sequence] = None, *,
                       verify: bool = True) -> AnonymizationResult:
    """
    Полный конвейер + статистика: сколько сырых спанов нашёл каждый детектор
    (на фазе детекции, ДО слияния). Недоступный детектор даёт 0.

    detectors — какие детекторы запускать. По умолчанию (None) — все включённые
    в config.DETECTORS_ENABLED; выключенный детектор не запускается и не попадает
    в spans_found. Явно переданный список выполняется как есть, без фильтра по
    конфигу — так /anonymize/{detector} и eval-скрипты могут изолированно гонять
    любой детектор (см. эндпоинт /anonymize/{detector}).
    verify=False отключает финальный добор через LLM — нужно для изолированного
    прогона одного детектора, чтобы он не дёргал сеть и не подмешивал чужие находки.
    """
    if detectors is None:
        detectors = [d for d in DETECTORS if is_detector_enabled(d.NAME)]
    spans: List[Span] = []
    spans_found: Dict[str, int] = {}
    for det in detectors:
        try:
            found = det.detect(text)
        except Exception as e:  # детектор не должен ронять пайплайн
            log.warning("Детектор %s упал: %s", det.NAME, e)
            found = []
        spans_found[det.NAME] = len(found)
        spans.extend(found)
    log.info("Сырые находки по детекторам: %s", spans_found)

    # 5. Разбор персон на компоненты имени.
    spans = split_persons(text, spans)
    # 5а. Убираем типы, которые по конфигу не маскируем (до слияния, чтобы их
    #     символы не «закрашивались» и могли достаться включённым типам).
    spans = [s for s in spans if is_type_enabled(s.type)]
    # 5б. Пер-детекторный фильтр: каждый источник заменяет только разрешённые ему
    #     типы (config.DETECTOR_TYPES). Детектор находит всё, но в финальную замену
    #     попадают только разрешённые типы. Применяется и к явному списку детекторов.
    spans = [s for s in spans if is_detector_type_enabled(s.source, s.type)]
    # 6. Слияние пересечений и склейка адресов.
    spans = merge_spans(text, spans)
    # 7. Замена с конца текста.
    masked = apply_spans(text, spans)
    # 8. Финальная проверка через LLM (если LMStudio доступен — иначе вернёт как есть).
    if verify:
        masked = verify_with_llm(masked, LMSTUDIO["max_verify_passes"])
    # 9. Свернуть тонкие метки в обобщающие: [Имя]/[Фамилия]/[Отчество]→[ФИО], [Локация]→[Адрес].
    masked = relabel_groups(masked)
    # 10. Самый конец: схлопнуть подряд идущие одинаковые метки ([X] [X] -> [X]).
    masked = collapse_repeated_labels(masked)

    return AnonymizationResult(text=masked, spans_found=spans_found)


def anonymize(text: str) -> str:
    """Простой вызов: только обезличенный текст (для отправки во внешнюю LLM)."""
    return anonymize_detailed(text).text
