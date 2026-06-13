# -*- coding: utf-8 -*-
"""Демонстрация: python -m anonymizer"""

from __future__ import annotations

import logging
import sys

from .pipeline import anonymize_detailed

EXAMPLES = [
    "Иванов Иван Иванович, тел. +7 916 123-45-67, "
    "email ivan.ivanov@example.com.",
    "ООО «Ромашка» из г. Уфа, ул. Ленина, д. 5 перечислило "
    "1 500 000 рублей 12 января 2023 года.",
    "Паспорт 45 12 345678, ИНН 7707083893, СНИЛС 112-233-445 95, "
    "карта 4276 3800 1234 5678, IP 192.168.0.1.",
]


def main() -> None:
    # На Windows консоль может быть не в UTF-8 — принудительно переключаем оба
    # потока (stdout — для print, stderr — для логов).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    for ex in EXAMPLES:
        result = anonymize_detailed(ex)
        stats = ", ".join(f"{name}={cnt}" for name, cnt in result.spans_found.items())
        print("ДО:      ", ex)
        print("ПОСЛЕ:   ", result.text)
        print("ДЕТЕКТОРЫ: ", stats)
        print("-" * 70)


if __name__ == "__main__":
    main()
