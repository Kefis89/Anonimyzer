# -*- coding: utf-8 -*-
"""Слияние пересекающихся спанов и замена их метками."""

from __future__ import annotations

import re
from typing import List, Optional

from .config import LABEL_GROUPS, LABELS, PRIORITY
from .span import Span

# Символы, через которые соседние однотипные адресные фрагменты можно склеивать.
_GLUE_GAP = re.compile(r"[\s.,;:№#\-()]*")

# Подряд идущие ОДИНАКОВЫЕ метки (обратная ссылка \1 требует точного совпадения).
_REPEATED_LABEL = re.compile(r"(\[[^\]]+\])(?:\s*\1)+")

# Текстовая карта «метка → обобщающая метка» для финальной группировки
# (config.LABEL_GROUPS, типы → текст меток). Компилируется один раз при импорте.
_GROUP_RELABEL = {
    LABELS[src]: LABELS[dst]
    for src, dst in LABEL_GROUPS.items()
    if src in LABELS and dst in LABELS
}
_GROUP_RELABEL_RE = (
    re.compile("|".join(re.escape(k) for k in _GROUP_RELABEL)) if _GROUP_RELABEL else None
)


def relabel_groups(text: str) -> str:
    """
    Сворачивает тонкие метки в обобщающие по config.LABEL_GROUPS:
    [Имя]/[Фамилия]/[Отчество] → [ФИО], [Локация] → [Адрес]. Применяется перед
    collapse_repeated_labels, который затем схлопывает образовавшиеся соседние
    одинаковые метки в одну (разбитое на части ФИО → один [ФИО]).
    """
    if _GROUP_RELABEL_RE is None:
        return text
    return _GROUP_RELABEL_RE.sub(lambda m: _GROUP_RELABEL[m.group(0)], text)


def collapse_repeated_labels(text: str) -> str:
    """
    Схлопывает подряд идущие одинаковые метки в одну: '[X] [X]' -> '[X]'.
    Разные соседние метки ('[Имя] [Фамилия]') не трогает. Применяется самым
    последним шагом конвейера, после всех детекторов, слияния и проверки LLM.
    """
    return _REPEATED_LABEL.sub(r"\1", text)


def merge_spans(text: str, spans: List[Span]) -> List[Span]:
    """
    Объединяем пересекающиеся спаны: на каждом символе побеждает метка с бóльшим
    PRIORITY (структурированные ID и компоненты имени важнее общих ORG/LOC/DATE).
    Реализовано «закрашиванием» символов — это даёт полное покрытие и корректную
    обработку частичных пересечений. Затем склеиваем соседние адресные фрагменты,
    разделённые только пунктуацией (AddrExtractor дробит адрес на «г. Уфа»,
    «ул. Ленина», «д. 5» — их нужно собрать в один [Адрес]).
    """
    if not spans:
        return []
    n = len(text)
    owner_type: List[Optional[str]] = [None] * n
    owner_pr = [-1] * n
    for sp in spans:
        pr = PRIORITY.get(sp.type, 0)
        for i in range(max(sp.start, 0), min(sp.stop, n)):
            if pr > owner_pr[i]:
                owner_pr[i] = pr
                owner_type[i] = sp.type

    # Собираем смежные «закрашенные» участки одного типа в спаны.
    merged: List[Span] = []
    i = 0
    while i < n:
        t = owner_type[i]
        if t is None:
            i += 1
            continue
        j = i
        while j < n and owner_type[j] == t:
            j += 1
        merged.append(Span(i, j, t, "merged"))
        i = j

    # Склейка соседних адресных фрагментов через пунктуацию/пробелы.
    glued: List[Span] = []
    for sp in merged:
        if glued:
            prev = glued[-1]
            gap = text[prev.stop:sp.start]
            if (sp.type == prev.type == "address"
                    and _GLUE_GAP.fullmatch(gap)):
                glued[-1] = Span(prev.start, sp.stop, "address", "merged")
                continue
        glued.append(sp)
    return glued


def apply_spans(text: str, spans: List[Span]) -> str:
    """Заменяем спаны метками. Идём с конца, чтобы не сбивать смещения."""
    for sp in sorted(spans, key=lambda s: s.start, reverse=True):
        # Обрезаем пробелы по краям спана — иначе захваченный детектором пробел
        # «съедается» меткой и соседние метки слипаются ([Сумма][Дата]).
        start, stop = sp.start, sp.stop
        while start < stop and text[start].isspace():
            start += 1
        while stop > start and text[stop - 1].isspace():
            stop -= 1
        if start >= stop:
            continue
        label = LABELS.get(sp.type, "[ПДн]")
        text = text[:start] + label + text[stop:]
    return text
