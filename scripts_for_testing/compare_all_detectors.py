# -*- coding: utf-8 -*-
"""
Прогон примеров по каждому детектору по отдельности.

Читает examples.json (массив исходных текстов), прогоняет КАЖДЫЙ текст через
КАЖДЫЙ детектор отдельно (тот же механизм, что у эндпоинта /anonymize/{detector}:
anonymize_detailed(text, [module], verify=False)) и пишет results.json — по записи
на пару (пример × детектор) с числом найденных спанов и обезличенным текстом.

Запуск:  .venv\\Scripts\\python.exe scripts_for_testing\\compare_all_detectors.py

После записи results.json автоматически строится report.html
(вызовом make_compare_report).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Скрипт лежит в подпапке scripts_for_testing/ — добавляем корень проекта в
# sys.path, чтобы импортировался пакет anonymizer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anonymizer.detectors import DETECTORS_BY_NAME
from anonymizer.pipeline import anonymize_detailed

BASE = Path(__file__).resolve().parent
EXAMPLES_FILE = BASE / "examples.json"
RESULTS_DIR = BASE / "results"
RESULTS_FILE = RESULTS_DIR / "results.json"

# Метка-заглушка в обезличенном тексте, напр. [Имя], [Адрес].
_LABEL = re.compile(r"\[[^\]]+\]")


def main() -> None:
    # На Windows консоль может быть не в UTF-8 — переключаем оба потока.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    examples = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    results = []
    for i, text in enumerate(examples):
        for name, module in DETECTORS_BY_NAME.items():
            res = anonymize_detailed(text, [module], verify=False)
            count = res.spans_found.get(name, 0)
            labels = len(_LABEL.findall(res.text))
            results.append({
                "example_index": i,
                "example": text,
                "detector": name,
                "spans_found": count,
                "labels_in_text": labels,
                "text": res.text,
            })
            print(f"[{i}] {name}: spans={count}, labels={labels}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nГотово: {len(results)} записей → {RESULTS_FILE}")

    # Сразу строим HTML-отчёт по только что записанному JSON. make_compare_report —
    # сосед по папке, только stdlib, anonymizer не импортирует.
    import make_compare_report
    make_compare_report.main()


if __name__ == "__main__":
    main()
