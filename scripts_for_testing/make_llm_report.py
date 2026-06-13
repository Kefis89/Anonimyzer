# -*- coding: utf-8 -*-
"""
Сравнительная таблица из llm_impact.json (Вариант 1: 3 детектора vs
Вариант 2: 4 + verify).

Читает llm_impact.json (его пишет compare_llm.py) и генерирует самодостаточный
llm_report.html: сводка сверху + построчное сравнение двух вариантов с колонкой
«Результат совпадает» (да/нет — совпал ли итоговый текст).

Только stdlib; НЕ импортирует anonymizer.

Запуск:  .venv\\Scripts\\python.exe scripts_for_testing\\make_llm_report.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS_DIR = BASE / "results"
DATA_FILE = RESULTS_DIR / "llm_impact.json"
REPORT_FILE = RESULTS_DIR / "llm_report.html"

_LABEL = re.compile(r"\[[^\]]+\]")

_STYLE = """
:root { --bd: #d9dee5; --muted: #8a93a2; --bg2: #f6f8fa; --lbl: #fde68a; }
* { box-sizing: border-box; }
body {
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #1c2430; margin: 0; padding: 32px; background: #fff;
}
.wrap { max-width: 1500px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 6px 0 0; }
h2 { font-size: 16px; margin: 28px 0 10px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid var(--bd); padding: 8px 10px; text-align: left; vertical-align: top; }
thead th { position: sticky; top: 0; background: #eef2f7; z-index: 1; }
tbody tr:nth-child(even) { background: var(--bg2); }
tbody tr.changed { background: #fff7ed; }
.idx { color: var(--muted); font-variant-numeric: tabular-nums; width: 34px; text-align: right; }
.src { width: 300px; }
.num { font-variant-numeric: tabular-nums; text-align: right; width: 110px; }
.masked { white-space: normal; word-break: break-word; }
.counts { margin-top: 6px; font-size: 12px; color: var(--muted); }
mark.lbl { background: var(--lbl); border-radius: 3px; padding: 0 3px; font-weight: 600; }
td.match { color: #15803d; font-weight: 700; text-align: center; width: 90px; }
td.diff  { color: #b91c1c; font-weight: 700; text-align: center; width: 90px; }
.summary table { width: auto; }
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

    if not DATA_FILE.exists():
        print(f"Нет {DATA_FILE.name}. Сначала запустите: python scripts_for_testing/compare_llm.py")
        return

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    s = data["summary"]
    items = data["items"]
    t1, t2 = s["test1_3detectors"], s["test2_4detectors"]

    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html lang="ru"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append("<title>Сравнение: 3 детектора vs 4 + verify</title>")
    out.append(f"<style>{_STYLE}</style></head><body><div class='wrap'>")
    out.append("<h1>Сравнение обезличивания: 3 детектора vs все 4 + проверка LLM</h1>")
    out.append(f"<p class='sub'>Примеров: {s['examples']} · LLM доступен: "
               f"{'да' if s['llm_available'] else 'нет'} · "
               f"LLM изменил результат: {s['examples_changed_by_llm']} из {s['examples']} · "
               f"доп. замен благодаря LLM: {s['extra_replacements_from_llm']}</p>")

    # --- Сводка ---
    out.append("<div class='summary'><h2>Итого</h2><table>")
    out.append("<thead><tr><th>Показатель</th><th class='num'>3 детектора</th>"
               "<th class='num'>4 + verify</th></tr></thead><tbody>")
    rows = [
        ("Σ найдено спанов", t1["total_spans"], t2["total_spans"]),
        ("Σ сделано замен", t1["total_replacements"], t2["total_replacements"]),
        ("Σ время, с", f"{t1['total_time_sec']:.2f}", f"{t2['total_time_sec']:.2f}"),
        ("Среднее, с/пример", f"{t1['avg_time_sec']:.3f}", f"{t2['avg_time_sec']:.3f}"),
    ]
    for label, a, b in rows:
        out.append(f"<tr><td>{label}</td><td class='num'>{a}</td><td class='num'>{b}</td></tr>")
    out.append("</tbody></table></div>")

    # --- Детально ---
    out.append("<h2>Детально</h2><table>")
    out.append("<thead><tr><th class='idx'>#</th><th class='src'>Исходный текст</th>"
               "<th>Вариант 1 · 3 детектора</th><th>Вариант 2 · 4 + verify</th>"
               "<th>Результат совпадает</th></tr></thead><tbody>")
    for it in items:
        changed = it["changed_by_llm"]
        rowcls = " class='changed'" if changed else ""
        out.append(f"<tr{rowcls}>")
        out.append(f"<td class='idx'>{it['example_index']}</td>")
        out.append(f"<td class='src'>{html.escape(it['example'], quote=False)}</td>")
        for key in ("test1", "test2"):
            t = it[key]
            out.append(
                f"<td class='masked'>{_esc(t['text'])}"
                f"<div class='counts'>спаны {t['spans_found']} · замен {t['replacements']} · "
                f"{t['time_sec']:.2f} с</div></td>")
        if changed:
            out.append("<td class='diff'>нет</td>")
        else:
            out.append("<td class='match'>да</td>")
        out.append("</tr>")
    out.append("</tbody></table></div></body></html>")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"Готово → {REPORT_FILE}")


if __name__ == "__main__":
    main()
