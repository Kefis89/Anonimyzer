# -*- coding: utf-8 -*-
"""Разбор персон: person-спан → [Имя]/[Фамилия]/[Отчество]."""

from __future__ import annotations

import re
from typing import List

from .config import log
from .detectors import natasha as natasha_detector
from .span import Span


def split_persons(text: str, spans: List[Span]) -> List[Span]:
    """
    Каждый person-спан раскладываем на [Имя]/[Фамилия]/[Отчество].

    NamesExtractor нельзя запускать на произвольном тексте (путает должности с
    фамилиями), поэтому вызываем его ТОЛЬКО на подстроке уже подтверждённого
    спана персоны. Он возвращает поверхностные (склонённые) формы без позиций —
    позицию каждой части ищем по границе слова \\b...\\b внутри спана, затем
    раскладываем слева направо без пересечений. Не разобралось — оставляем [ФИО].
    """
    n = natasha_detector.NATASHA
    result: List[Span] = []
    for sp in spans:
        if sp.type != "person":
            result.append(sp)
            continue
        if not n:
            result.append(sp)   # без Natasha разложить нечем → [ФИО]
            continue

        sub = text[sp.start:sp.stop]
        comps = []  # (тип-компонента, поверхностная форма)
        try:
            for m in n["names"](sub):
                fact = m.fact
                if fact.last:
                    comps.append(("surname", fact.last))
                if fact.first:
                    comps.append(("name", fact.first))
                if fact.middle:
                    comps.append(("patronymic", fact.middle))
        except Exception as e:
            log.warning("NamesExtractor: ошибка, спан остаётся [ФИО]: %s", e)

        # Находим позицию каждой формы по границе слова; \b в Python работает
        # с кириллицей (\w включает кириллицу), поэтому на неё можно опираться.
        located = []
        for etype, form in comps:
            m = re.search(r"\b" + re.escape(form) + r"\b", sub)
            if m:
                located.append((m.start(), m.end(), etype))
        located.sort()

        # Раскладка слева направо без пересечений.
        final = []
        last_end = -1
        for s, e, etype in located:
            if s >= last_end:
                final.append(Span(sp.start + s, sp.start + e, etype, sp.source))
                last_end = e

        result.extend(final if final else [sp])
    return result
