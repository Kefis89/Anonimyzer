# -*- coding: utf-8 -*-
"""
Оценка вклада LLM-детектора в обезличивание.

Каждый пример из examples.json прогоняется в двух конфигурациях:
  Тест 1 (база):   regex + natasha + presidio, без LLM и без verify;
  Тест 2 (полный): все 4 детектора + финальная проверка через LLM (verify).

Для каждой конфигурации фиксируем: сколько найдено спанов (сырые находки
детекторов), сколько сделано замен (меток [...] в итоговом тексте) и сам текст.
Сводка показывает, насколько важен LLM: где он изменил результат и сколько
добавил замен.

Запуск:  .venv\\Scripts\\python.exe scripts_for_testing\\compare_llm.py [N]
         N — прогнать только первые N примеров (по умолчанию все). Полезно, т.к.
         Тест 2 делает до 3 запросов к LMStudio на пример (медленно).

После записи llm_impact.json автоматически строится llm_report.html
(вызовом make_llm_report).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# Скрипт лежит в подпапке scripts_for_testing/ — добавляем корень проекта в
# sys.path, чтобы импортировался пакет anonymizer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anonymizer.detectors import DETECTORS, llm
from anonymizer.pipeline import anonymize_detailed

BASE = Path(__file__).resolve().parent
EXAMPLES_FILE = BASE / "examples.json"
RESULTS_DIR = BASE / "results"
RESULTS_FILE = RESULTS_DIR / "llm_impact.json"

# Базовая тройка в каноническом порядке (важен для merge): regex, natasha, presidio.
BASE3 = [d for d in DETECTORS if d.NAME != "llm"]

# Метка-заглушка в обезличенном тексте.
_LABEL = re.compile(r"\[[^\]]+\]")


def _replacements(text: str) -> int:
    return len(_LABEL.findall(text))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    llm_ok = llm.available()
    if not llm_ok:
        print("ВНИМАНИЕ: LMStudio/LLM недоступен — Тест 2 будет ≈ Тесту 1, "
              "сравнение неинформативно. Поднимите LMStudio и перезапустите.\n")

    examples = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    limit = None
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
        examples = examples[:limit]

    items = []
    for i, text in enumerate(examples):
        s1 = time.perf_counter()
        r1 = anonymize_detailed(text, BASE3, verify=False)
        t1_time = time.perf_counter() - s1

        s2 = time.perf_counter()
        r2 = anonymize_detailed(text)  # все 4 + verify=True
        t2_time = time.perf_counter() - s2

        t1_spans, t1_repl = sum(r1.spans_found.values()), _replacements(r1.text)
        t2_spans, t2_repl = sum(r2.spans_found.values()), _replacements(r2.text)
        changed = r1.text != r2.text

        items.append({
            "example_index": i,
            "example": text,
            "test1": {
                "detectors": [d.NAME for d in BASE3], "verify": False,
                "spans_found": t1_spans, "replacements": t1_repl,
                "time_sec": round(t1_time, 4), "text": r1.text,
            },
            "test2": {
                "detectors": [d.NAME for d in DETECTORS], "verify": True,
                "spans_found": t2_spans, "replacements": t2_repl,
                "time_sec": round(t2_time, 4), "text": r2.text,
            },
            "changed_by_llm": changed,
        })
        flag = "≠" if changed else "="
        print(f"[{i}] 3п: spans={t1_spans} repl={t1_repl} t={t1_time:.2f}s  |  "
              f"4п+verify: spans={t2_spans} repl={t2_repl} t={t2_time:.2f}s  {flag}")

    # --- сводка ---
    n = len(items)
    t1_total_spans = sum(it["test1"]["spans_found"] for it in items)
    t1_total_repl = sum(it["test1"]["replacements"] for it in items)
    t2_total_spans = sum(it["test2"]["spans_found"] for it in items)
    t2_total_repl = sum(it["test2"]["replacements"] for it in items)
    changed_cnt = sum(1 for it in items if it["changed_by_llm"])
    extra_repl = sum(max(0, it["test2"]["replacements"] - it["test1"]["replacements"])
                     for it in items)
    t1_total_time = sum(it["test1"]["time_sec"] for it in items)
    t2_total_time = sum(it["test2"]["time_sec"] for it in items)
    t1_avg = t1_total_time / n if n else 0.0
    t2_avg = t2_total_time / n if n else 0.0

    summary = {
        "examples": n,
        "llm_available": llm_ok,  # доступен ли LLM-детектор (LMStudio поднят)
        "test1_3detectors": {
            "total_spans": t1_total_spans, "total_replacements": t1_total_repl,
            "total_time_sec": round(t1_total_time, 4), "avg_time_sec": round(t1_avg, 4),
        },
        "test2_4detectors": {
            "total_spans": t2_total_spans, "total_replacements": t2_total_repl,
            "total_time_sec": round(t2_total_time, 4), "avg_time_sec": round(t2_avg, 4),
        },
        "examples_changed_by_llm": changed_cnt,
        "extra_replacements_from_llm": extra_repl,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n================ СВОДКА ================")
    print(f"Примеров: {n}   (LLM доступен: {'да' if llm_ok else 'НЕТ'})")
    print(f"                  3 детектора    4 + verify")
    print(f"Σ найдено спанов  {t1_total_spans:>8}    {t2_total_spans:>10}")
    print(f"Σ сделано замен   {t1_total_repl:>8}    {t2_total_repl:>10}")
    print(f"Σ время, с        {t1_total_time:>8.2f}    {t2_total_time:>10.2f}")
    print(f"Среднее, с/пример {t1_avg:>8.3f}    {t2_avg:>10.3f}")
    print(f"Примеров, где LLM изменил результат: {changed_cnt} из {n}")
    print(f"Доп. замен благодаря LLM: {extra_repl}")
    print(f"\nГотово → {RESULTS_FILE}")

    # Сразу строим HTML-отчёт по только что записанному JSON. make_llm_report —
    # сосед по папке, только stdlib, anonymizer не импортирует.
    import make_llm_report
    make_llm_report.main()


if __name__ == "__main__":
    main()
