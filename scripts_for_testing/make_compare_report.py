# -*- coding: utf-8 -*-
"""
Генерация веб-страницы (таблицы) из results.json.

Читает results.json и пишет самодостаточный report.html с вшитыми данными:
открывается двойным кликом, без сервера и без интернета. Раскладка — матрица
пример × детектор плюс сводка сверху.

Только stdlib; НЕ импортирует anonymizer (иначе при импорте грузятся модели и
идёт проба LMStudio — а нам нужно лишь прочитать готовый JSON).

Запуск:  .venv\\Scripts\\python.exe scripts_for_testing\\make_compare_report.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS_DIR = BASE / "results"
RESULTS_FILE = RESULTS_DIR / "results.json"
REPORT_FILE = RESULTS_DIR / "report.html"

# Метка-заглушка в обезличенном тексте, напр. [Имя], [Адрес].
_LABEL = re.compile(r"\[[^\]]+\]")

_STYLE = """
:root { --bd: #d9dee5; --muted: #8a93a2; --bg2: #f6f8fa; --lbl: #fde68a; }
* { box-sizing: border-box; }
body {
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #1c2430; margin: 0; padding: 32px; background: #fff;
}
.wrap { max-width: 1400px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 0 0 24px; }
h2 { font-size: 16px; margin: 28px 0 10px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid var(--bd); padding: 8px 10px; text-align: left; vertical-align: top; }
thead th { position: sticky; top: 0; background: #eef2f7; z-index: 1; }
tbody tr:nth-child(even) { background: var(--bg2); }
.idx { color: var(--muted); font-variant-numeric: tabular-nums; width: 34px; text-align: right; }
.src { width: 320px; }
.num { font-variant-numeric: tabular-nums; text-align: right; width: 80px; }
.masked { white-space: normal; word-break: break-word; }
.empty { color: var(--muted); }
.counts { margin-top: 6px; font-size: 12px; color: var(--muted); }
mark.lbl { background: var(--lbl); border-radius: 3px; padding: 0 3px; font-weight: 600; }
.summary table { width: auto; }
.summary td.num, .summary th.num { width: 110px; }
"""


def _esc(text: str) -> str:
    """Экранируем текст и подсвечиваем метки [...]."""
    safe = html.escape(text, quote=False)
    return _LABEL.sub(r'<mark class="lbl">\g<0></mark>', safe)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not RESULTS_FILE.exists():
        print(f"Нет {RESULTS_FILE.name}. Сначала запустите: python scripts_for_testing/compare_all_detectors.py")
        return

    records = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    # Детекторы в порядке первого появления; данные по примерам.
    detectors: list[str] = []
    by_example: dict[int, dict] = {}
    for r in records:
        if r["detector"] not in detectors:
            detectors.append(r["detector"])
        ex = by_example.setdefault(r["example_index"], {"example": r["example"], "cells": {}})
        ex["cells"][r["detector"]] = r

    # Сводка по детекторам.
    totals = {p: {"spans": 0, "labels": 0} for p in detectors}
    for r in records:
        totals[r["detector"]]["spans"] += r["spans_found"]
        totals[r["detector"]]["labels"] += r["labels_in_text"]

    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html lang="ru"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append("<title>Сравнение детекторов</title>")
    out.append(f"<style>{_STYLE}</style></head><body><div class='wrap'>")
    out.append("<h1>Сравнение детекторов обезличивания</h1>")
    out.append(f"<p class='sub'>{len(by_example)} примеров × {len(detectors)} детектора. "
               "Метки подсвечены; «спаны» — сырые находки детектора, «метки» — заглушки в тексте.</p>")

    # --- Сводка ---
    out.append("<div class='summary'><h2>Итого по детекторам</h2><table>")
    out.append("<thead><tr><th>Детектор</th><th class='num'>Σ спанов</th>"
               "<th class='num'>Σ меток</th></tr></thead><tbody>")
    for p in detectors:
        out.append(f"<tr><td>{html.escape(p)}</td>"
                   f"<td class='num'>{totals[p]['spans']}</td>"
                   f"<td class='num'>{totals[p]['labels']}</td></tr>")
    out.append("</tbody></table></div>")

    # --- Матрица пример × детектор ---
    out.append("<h2>Детально</h2><table>")
    out.append("<thead><tr><th class='idx'>#</th><th class='src'>Исходный текст</th>")
    for p in detectors:
        out.append(f"<th>{html.escape(p)}</th>")
    out.append("</tr></thead><tbody>")

    for idx in sorted(by_example):
        ex = by_example[idx]
        out.append("<tr>")
        out.append(f"<td class='idx'>{idx}</td>")
        out.append(f"<td class='src'>{html.escape(ex['example'], quote=False)}</td>")
        for p in detectors:
            rec = ex["cells"].get(p)
            if rec is None:
                out.append("<td class='empty'>—</td>")
                continue
            cls = "masked empty" if rec["spans_found"] == 0 else "masked"
            out.append(
                f"<td class='{cls}'>{_esc(rec['text'])}"
                f"<div class='counts'>спаны {rec['spans_found']} · "
                f"метки {rec['labels_in_text']}</div></td>")
        out.append("</tr>")
    out.append("</tbody></table></div></body></html>")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"Готово → {REPORT_FILE}")


if __name__ == "__main__":
    main()
