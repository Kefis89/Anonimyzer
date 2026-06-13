# -*- coding: utf-8 -*-
"""Детектор 1: regex — структурированные идентификаторы. Всегда доступен."""

from __future__ import annotations

from typing import List

from ..config import REGEXES
from ..span import Span

NAME = "regex"


def available() -> bool:
    return True


def detect(text: str) -> List[Span]:
    spans: List[Span] = []
    for etype, pattern in REGEXES.items():
        for m in pattern.finditer(text):
            spans.append(Span(m.start(), m.end(), etype, NAME))
    return spans
