# -*- coding: utf-8 -*-
"""
Детектор 2: Natasha — NER (PER/LOC/ORG) + экстракторы адреса/даты/суммы.

Объекты Natasha загружаются СРАЗУ при импорте модуля (не лениво). Если библиотека
не установлена — детектор молча отключается (NATASHA = None), импорт не падает,
пайплайн продолжает работу на остальных детекторах.
"""

from __future__ import annotations

from typing import List

from ..config import log
from ..span import Span

NAME = "natasha"


def _load():
    """Загружает объекты Natasha. None — если библиотека недоступна."""
    try:
        from natasha import (
            Doc, Segmenter, MorphVocab, NewsEmbedding, NewsNERTagger,
            AddrExtractor, DatesExtractor, MoneyExtractor, NamesExtractor,
        )
        morph_vocab = MorphVocab()
        emb = NewsEmbedding()
        return {
            "Doc": Doc,
            "segmenter": Segmenter(),
            "ner": NewsNERTagger(emb),
            "addr": AddrExtractor(morph_vocab),
            "dates": DatesExtractor(morph_vocab),
            "money": MoneyExtractor(morph_vocab),
            "names": NamesExtractor(morph_vocab),
        }
    except Exception as e:  # библиотека не установлена и т.п.
        log.warning("Natasha недоступна, детектор пропущен: %s", e)
        return None


# Загружается заранее, при импорте модуля.
NATASHA = _load()


def available() -> bool:
    return NATASHA is not None


def detect(text: str) -> List[Span]:
    if NATASHA is None:
        return []
    spans: List[Span] = []
    try:
        doc = NATASHA["Doc"](text)
        doc.segment(NATASHA["segmenter"])
        doc.tag_ner(NATASHA["ner"])
        ner_map = {"PER": "person", "LOC": "loc", "ORG": "org"}
        for s in doc.spans:
            etype = ner_map.get(s.type)
            if etype:
                spans.append(Span(s.start, s.stop, etype, NAME))
        # Rule-based экстракторы (возвращают yargy-матчи со .start/.stop).
        for m in NATASHA["addr"](text):
            spans.append(Span(m.start, m.stop, "address", NAME))
        for m in NATASHA["dates"](text):
            spans.append(Span(m.start, m.stop, "date", NAME))
        for m in NATASHA["money"](text):
            spans.append(Span(m.start, m.stop, "money", NAME))
    except Exception as e:
        log.warning("Natasha: ошибка разбора, частичный результат: %s", e)
    return spans
