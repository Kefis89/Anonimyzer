# -*- coding: utf-8 -*-
"""Модель данных: найденный фрагмент персональных данных."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Span:
    """Найденный фрагмент ПДн: полуинтервал [start, stop) и его тип/источник."""
    start: int
    stop: int
    type: str     # ключ в LABELS / PRIORITY
    source: str   # 'regex' | 'natasha' | 'presidio' | 'llm' | 'merged'
