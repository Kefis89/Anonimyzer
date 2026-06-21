# -*- coding: utf-8 -*-
"""
Тесты для пакета anonymizer.

Запуск:  python -m pytest -v   (нужен pytest: pip install pytest)

Принципы:
- Юнит-тесты чистых функций (regex / merge / apply / parse_entities) не требуют
  зависимостей и выполняются всегда.
- Тесты, которым нужна Natasha/Presidio, помечены skipif — в regex-only среде они
  не падают, а пропускаются.
- LMStudio (LLM) глобально отключён autouse-фикстурой, чтобы тесты были
  детерминированными и не ходили в сеть; разбор ответа LLM проверяется отдельно
  на готовом JSON через llm.parse_entities.
"""

import pytest

from anonymizer import anonymize, anonymize_detailed, config
from anonymizer.merge import (
    apply_spans, collapse_repeated_labels, merge_spans, relabel_groups,
)
from anonymizer.persons import split_persons
from anonymizer.span import Span
from anonymizer.detectors import DETECTORS, llm, natasha, presidio, regex

# Доступность опциональных детекторов определяем один раз при сборе тестов.
HAS_NATASHA = natasha.available()
HAS_PRESIDIO = presidio.available()

needs_natasha = pytest.mark.skipif(not HAS_NATASHA, reason="нужна Natasha (NER/NamesExtractor)")
needs_presidio = pytest.mark.skipif(not HAS_PRESIDIO, reason="нужен Presidio + модель spaCy ru")


@pytest.fixture(autouse=True)
def disable_lmstudio(monkeypatch):
    """Отключаем LLM/LMStudio во всех тестах: детерминизм и никаких сетевых вызовов."""
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", None)


# --- хелперы ---------------------------------------------------------------

def regex_mask(text: str) -> str:
    """Маскировка только regex-детектором (без моделей)."""
    return apply_spans(text, merge_spans(text, regex.detect(text)))


def person_mask(text: str) -> str:
    """Прогон текста как единого подтверждённого person-спана через разбор ФИО."""
    spans = split_persons(text, [Span(0, len(text), "person", "test")])
    return apply_spans(text, merge_spans(text, spans))


def triples(spans):
    """Спаны → сравнимые кортежи (start, stop, type)."""
    return [(s.start, s.stop, s.type) for s in spans]


# ===========================================================================
#  1. Структурированные ID — regex
# ===========================================================================

class TestRegexStructuredIDs:
    def test_email(self):
        out = regex_mask("пишите на ivan.ivanov@example.com")
        assert "[Email]" in out and "ivan.ivanov@example.com" not in out

    @pytest.mark.parametrize("text,raw", [
        ("звоните +7 916 123-45-67 срочно", "+7 916 123-45-67"),
        ("тел 8 (495) 123-45-67", "8 (495) 123-45-67"),
        ("номер 495 123-45-67", "495 123-45-67"),       # без префикса
        ("местный 123-45-67", "123-45-67"),             # 7-значный локальный
    ])
    def test_phone_formats(self, text, raw):
        out = regex_mask(text)
        assert "[Телефон]" in out and raw not in out

    def test_card(self):
        out = regex_mask("карта 4276 3800 1234 5678")
        assert "[БанковскаяКарта]" in out and "4276 3800 1234 5678" not in out

    def test_snils(self):
        out = regex_mask("СНИЛС 112-233-445 95")
        assert "[СНИЛС]" in out and "112-233-445 95" not in out

    def test_ip(self):
        out = regex_mask("сервер 192.168.0.1 доступен")
        assert "[IP]" in out and "192.168.0.1" not in out

    def test_passport(self):
        out = regex_mask("Паспорт 45 12 345678")
        assert "[Паспорт]" in out and "45 12 345678" not in out

    def test_bare_inn_is_inn_not_passport(self):
        """Ключевой нюанс: голый 10-значный ИНН → [ИНН], а НЕ [Паспорт]."""
        out = regex_mask("ИНН 7707083893")
        assert "[ИНН]" in out
        assert "[Паспорт]" not in out
        assert "7707083893" not in out

    @pytest.mark.parametrize("text", [
        "сумма 1 500 000 рублей",
        "цена $1000",
        "всего 99.99 ₽",
        "5 млн рублей",
        "итого 2500 USD",
    ])
    def test_money_with_currency(self, text):
        assert "[Сумма]" in regex_mask(text)

    @pytest.mark.parametrize("text", [
        "просто число 1500000",          # нет валюты → не сумма
        "в рубильнике 5 контактов",      # \b не даёт зацепить «руб» в слове
    ])
    def test_money_requires_currency(self, text):
        assert "[Сумма]" not in regex_mask(text)


# ===========================================================================
#  2. Слияние пересекающихся спанов — merge_spans
# ===========================================================================

class TestMergeSpans:
    def test_overlap_higher_priority_wins(self):
        # ИНН(95) и телефон(100) на одном диапазоне → побеждает телефон.
        merged = merge_spans("7707083893",
                             [Span(0, 10, "inn", "x"), Span(0, 10, "phone", "x")])
        assert triples(merged) == [(0, 10, "phone")]

    def test_partial_overlap_split(self):
        # date(30) 0..6 и money(60) 3..10 → date уступает money на пересечении.
        merged = merge_spans("abcdefghij",
                             [Span(0, 6, "date", "x"), Span(3, 10, "money", "x")])
        assert triples(merged) == [(0, 3, "date"), (3, 10, "money")]

    def test_nested_higher_priority(self):
        # phone(100) внутри loc(40) → loc разрывается на две части.
        merged = merge_spans("abcdefghij",
                             [Span(0, 10, "loc", "x"), Span(3, 6, "phone", "x")])
        assert triples(merged) == [(0, 3, "loc"), (3, 6, "phone"), (6, 10, "loc")]

    def test_empty(self):
        assert merge_spans("текст", []) == []


# ===========================================================================
#  3. Склейка многочастного адреса в один [Адрес]
# ===========================================================================

class TestAddressGlue:
    def test_glue_fragments(self):
        # AddrExtractor дробит адрес на части — соседние склеиваются через пунктуацию.
        t = "г. Уфа, ул. Ленина, д. 5"
        frags = [Span(0, 6, "address", "x"),    # «г. Уфа»
                 Span(8, 18, "address", "x"),   # «ул. Ленина»
                 Span(20, 24, "address", "x")]  # «д. 5»
        merged = merge_spans(t, frags)
        assert triples(merged) == [(0, 24, "address")]
        assert apply_spans(t, merged) == "[Адрес]"

    def test_non_address_not_glued(self):
        # Склейка через пунктуацию работает только для адресов.
        t = "Анна, Олег"
        frags = [Span(0, 4, "name", "x"), Span(6, 10, "name", "x")]
        assert triples(merge_spans(t, frags)) == [(0, 4, "name"), (6, 10, "name")]

    @needs_natasha
    def test_glue_integration(self):
        t = "Адрес: г. Уфа, ул. Ленина, д. 5."
        masked = apply_spans(t, merge_spans(t, natasha.detect(t)))
        assert masked.count("[Адрес]") == 1


# ===========================================================================
#  4. Разбор ФИО — split_persons (нужна Natasha)
# ===========================================================================

@needs_natasha
class TestSplitPersons:
    def test_full_name(self):
        assert person_mask("Иван Петров") == "[Имя] [Фамилия]"

    def test_declined_full_name(self):
        assert person_mask("Петрову Анну Сергеевну") == "[Фамилия] [Имя] [Отчество]"

    def test_initials(self):
        out = person_mask("Петров И.С.")
        assert "Петров" not in out
        assert "[Фамилия]" in out and "[Имя]" in out and "[Отчество]" in out

    def test_lone_surname_decomposes_to_component(self):
        # Одинокая фамилия не уходит в фолбэк — NamesExtractor делает из неё компонент.
        out = person_mask("Хмырь")
        assert "Хмырь" not in out
        assert out.startswith("[") and out.endswith("]")


# ===========================================================================
#  5. Фолбэк персоны и проброс не-персон (детерминированно)
# ===========================================================================

class TestPersonFallbackAndPassthrough:
    def test_fallback_to_fio_without_natasha(self, monkeypatch):
        # Без Natasha разложить персону нечем → остаётся [ФИО].
        monkeypatch.setattr(natasha, "NATASHA", None)
        t = "Иван Петров"
        spans = split_persons(t, [Span(0, len(t), "person", "test")])
        assert apply_spans(t, merge_spans(t, spans)) == "[ФИО]"

    def test_non_person_spans_pass_through(self, monkeypatch):
        monkeypatch.setattr(natasha, "NATASHA", None)
        t = "ivan@example.com"
        out = split_persons(t, [Span(0, len(t), "email", "regex")])
        assert triples(out) == [(0, len(t), "email")]


# ===========================================================================
#  6. Разбор ответа LLM — llm.parse_entities
# ===========================================================================

class TestParseLLMEntities:
    def test_type_mapping(self):
        j = ('{"entities":[{"type":"имя","text":"Анна"},'
             '{"type":"фамилия","text":"Петров"},'
             '{"type":"сумма","text":"5 руб"}]}')
        assert triples(llm.parse_entities(j, "Анна Петров 5 руб")) == \
            [(0, 4, "name"), (5, 11, "surname"), (12, 17, "money")]

    def test_all_occurrences_found(self):
        j = '{"entities":[{"type":"имя","text":"Анна"}]}'
        assert triples(llm.parse_entities(j, "Анна и Анна")) == \
            [(0, 4, "name"), (7, 11, "name")]

    def test_structured_types_filtered_out(self):
        # Структурированные ID игнорируются (зона regex/Presidio).
        j = ('{"entities":[{"type":"телефон","text":"123"},'
             '{"type":"инн","text":"7707083893"}]}')
        assert llm.parse_entities(j, "123 7707083893") == []

    def test_unknown_type_dropped(self):
        assert llm.parse_entities('{"entities":[{"type":"мусор","text":"Анна"}]}',
                                   "Анна") == []

    def test_malformed_json_returns_empty(self):
        assert llm.parse_entities("это не json", "Анна") == []

    def test_text_not_in_source_dropped(self):
        assert llm.parse_entities('{"entities":[{"type":"имя","text":"Олег"}]}',
                                   "Анна") == []


# ===========================================================================
#  7. Замена — apply_spans
# ===========================================================================

class TestApplySpans:
    def test_replacement_from_end_keeps_offsets(self):
        t = "X тут Y там"  # X@0, Y@6
        spans = [Span(0, 1, "name", "x"), Span(6, 7, "surname", "x")]
        assert apply_spans(t, spans) == "[Имя] тут [Фамилия] там"

    def test_edge_whitespace_trimmed(self):
        # Спан включает хвостовой пробел — он не должен «съесться» меткой.
        t = "сумма 100 руб и дата"
        sp = [Span(t.index("100"), t.index("и "), "money", "x")]  # «100 руб »
        assert apply_spans(t, sp) == "сумма [Сумма] и дата"

    def test_whitespace_only_span_skipped(self):
        assert apply_spans("a   b", [Span(1, 4, "money", "x")]) == "a   b"


# ===========================================================================
#  7b. Схлопывание подряд идущих одинаковых меток
# ===========================================================================

class TestCollapseRepeatedLabels:
    def test_two_same_collapse(self):
        assert collapse_repeated_labels("[Организация] [Организация]") == "[Организация]"

    def test_three_same_collapse(self):
        assert collapse_repeated_labels("[Адрес] [Адрес] [Адрес]") == "[Адрес]"

    def test_collapse_inside_text(self):
        assert collapse_repeated_labels("выдан [Организация] [Организация] [Адрес]") == \
            "выдан [Организация] [Адрес]"

    def test_different_labels_untouched(self):
        assert collapse_repeated_labels("[Фамилия] [Имя] [Отчество]") == \
            "[Фамилия] [Имя] [Отчество]"

    def test_non_adjacent_untouched(self):
        assert collapse_repeated_labels("[Адрес] [Дата]") == "[Адрес] [Дата]"


# ===========================================================================
#  8. Статистика детекторов (anonymize_detailed)
# ===========================================================================

class TestDetectorStats:
    def test_spans_found_shape_and_counts(self, monkeypatch):
        monkeypatch.setattr(natasha, "NATASHA", None)
        monkeypatch.setattr(presidio, "PRESIDIO", None)
        res = anonymize_detailed("ИНН 7707083893, IP 192.168.0.1")
        # Все четыре детектора присутствуют как ключи.
        assert set(res.spans_found) == {"regex", "natasha", "presidio", "llm"}
        assert res.spans_found["regex"] >= 2          # inn + ip
        assert res.spans_found["natasha"] == 0
        assert res.spans_found["presidio"] == 0
        assert res.spans_found["llm"] == 0           # LMStudio отключён
        assert "[ИНН]" in res.text and "[IP]" in res.text

    def test_anonymize_returns_str(self):
        assert isinstance(anonymize("просто текст"), str)


# ===========================================================================
#  9. Отказоустойчивость: пайплайн жив в режиме regex-only
# ===========================================================================

class TestFaultToleranceRegexOnly:
    def test_anonymize_runs_without_optional_detectors(self, monkeypatch):
        # Отключаем Natasha и Presidio (LMStudio уже выключен autouse-фикстурой).
        monkeypatch.setattr(natasha, "NATASHA", None)
        monkeypatch.setattr(presidio, "PRESIDIO", None)
        t = ("Паспорт 45 12 345678, ИНН 7707083893, "
             "карта 4276 3800 1234 5678, IP 192.168.0.1")
        out = anonymize(t)
        for label in ("[Паспорт]", "[ИНН]", "[БанковскаяКарта]", "[IP]"):
            assert label in out
        for raw in ("45 12 345678", "7707083893", "4276 3800 1234 5678", "192.168.0.1"):
            assert raw not in out

    def test_detectors_return_empty_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(natasha, "NATASHA", None)
        monkeypatch.setattr(presidio, "PRESIDIO", None)
        assert natasha.detect("Иван Петров") == []
        assert presidio.detect("Иван Петров") == []
        assert llm.detect("Иван Петров") == []     # LMStudio выключен


# ===========================================================================
#  10. Настройка типов для обезличивания (config.ANONYMIZE_TYPES)
# ===========================================================================

class TestAnonymizeTypeConfig:
    def test_config_covers_all_label_types(self):
        # Каждому типу-метке соответствует переключатель. По умолчанию включены
        # все, кроме money и date — суммы и даты осознанно не маскируются.
        assert set(config.ANONYMIZE_TYPES) == set(config.LABELS)
        assert not config.ANONYMIZE_TYPES["money"]
        assert not config.ANONYMIZE_TYPES["date"]
        assert all(v for t, v in config.ANONYMIZE_TYPES.items() if t not in ("money", "date"))

    def test_default_masks_email(self):
        res = anonymize_detailed("a@b.com", [regex], verify=False)
        assert res.text == "[Email]"

    def test_disabled_type_not_masked(self, monkeypatch):
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "email", False)
        res = anonymize_detailed("пишите на a@b.com и звоните +7 916 123-45-67",
                                 [regex], verify=False)
        assert "a@b.com" in res.text          # email не замаскирован
        assert "[Email]" not in res.text
        assert "[Телефон]" in res.text        # другой тип по-прежнему маскируется

    def test_disable_one_keeps_others(self, monkeypatch):
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "inn", False)
        res = anonymize_detailed("ИНН 7707083893, IP 192.168.0.1", [regex], verify=False)
        assert "7707083893" in res.text
        assert "[ИНН]" not in res.text
        assert "[IP]" in res.text

    def test_spans_found_unaffected_by_toggle(self, monkeypatch):
        # Конфиг гасит маскирование, но не обнаружение: спан всё равно посчитан.
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "email", False)
        res = anonymize_detailed("a@b.com", [regex], verify=False)
        assert res.spans_found["regex"] == 1
        assert "[Email]" not in res.text and "a@b.com" in res.text

    @needs_natasha
    def test_disable_name_component(self, monkeypatch):
        # Компоненты ФИО управляются по отдельности: гасим только имя. В выводе
        # компоненты обобщаются до [ФИО] (LABEL_GROUPS), но имя не маскируется.
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "name", False)
        res = anonymize_detailed("Иванов Иван Иванович", [natasha], verify=False)
        assert "[ФИО]" in res.text             # фамилия/отчество → [ФИО]
        assert "Иван" in res.text              # имя осталось в тексте
        assert "[Имя]" not in res.text

    def test_verify_skips_disabled_type(self, monkeypatch):
        # verify не должен добирать выключенный тип. Мокаем LMStudio без сети.
        monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "m")
        monkeypatch.setattr(llm, "_lmstudio_chat",
                            lambda system, text: '{"entities":[{"type":"дата","text":"7 июня"}]}')
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "date", False)
        out = llm.verify_with_llm("приём 7 июня", 1)
        assert "7 июня" in out and "[Дата]" not in out

    def test_verify_masks_enabled_type(self, monkeypatch):
        # Включённый тип verify добирает и маскирует (date включаем явно — по
        # умолчанию он выключен).
        monkeypatch.setitem(config.ANONYMIZE_TYPES, "date", True)
        monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "m")
        monkeypatch.setattr(llm, "_lmstudio_chat",
                            lambda system, text: '{"entities":[{"type":"дата","text":"7 июня"}]}')
        out = llm.verify_with_llm("приём 7 июня", 1)
        assert "[Дата]" in out and "7 июня" not in out


# ===========================================================================
#  11. Настройка детекторов (config.DETECTORS_ENABLED)
# ===========================================================================

class TestDetectorConfig:
    def test_config_covers_all_detectors(self):
        # Каждому детектору соответствует переключатель, по умолчанию все включены.
        assert set(config.DETECTORS_ENABLED) == {m.NAME for m in DETECTORS}
        assert all(config.DETECTORS_ENABLED.values())

    def test_disabled_detectors_not_run_by_default(self, monkeypatch):
        # Без явного списка работают только включённые детекторы; выключенные
        # не запускаются и не попадают в spans_found.
        for name in ("natasha", "presidio", "llm"):
            monkeypatch.setitem(config.DETECTORS_ENABLED, name, False)
        res = anonymize_detailed("ИНН 7707083893", verify=False)
        assert set(res.spans_found) == {"regex"}
        assert "[ИНН]" in res.text

    def test_explicit_list_bypasses_config(self, monkeypatch):
        # Явный список (как у /anonymize/{detector} и eval-скриптов) выполняется
        # как передан — выключенный в конфиге детектор всё равно запускается.
        monkeypatch.setitem(config.DETECTORS_ENABLED, "regex", False)
        res = anonymize_detailed("ИНН 7707083893", [regex], verify=False)
        assert res.spans_found == {"regex": 1}
        assert "[ИНН]" in res.text

    def test_disabled_llm_skips_verify(self, monkeypatch):
        # DETECTOR_LLM=False гасит и финальную LLM-проверку при живом LMStudio.
        monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "m")
        monkeypatch.setattr(llm, "_lmstudio_chat",
                            lambda system, text: '{"entities":[{"type":"дата","text":"7 июня"}]}')
        monkeypatch.setitem(config.DETECTORS_ENABLED, "llm", False)
        out = llm.verify_with_llm("приём 7 июня", 1)
        assert out == "приём 7 июня"


# ===========================================================================
#  12. Настройка типов на детектор (config.DETECTOR_TYPES)
# ===========================================================================

class TestDetectorTypeConfig:
    def test_config_covers_all_detectors(self):
        # Каждому детектору соответствует набор разрешённых типов, и все они —
        # подмножество известных типов-меток.
        assert set(config.DETECTOR_TYPES) == {m.NAME for m in DETECTORS}
        for allowed in config.DETECTOR_TYPES.values():
            assert allowed <= set(config.LABELS)

    def test_restriction_drops_replacement(self, monkeypatch):
        # Убираем inn из разрешённых типов regex: ИНН детектор всё ещё находит,
        # но в финальную замену он не попадает. Заодно проверяем, что фильтр
        # действует и для ЯВНОГО списка детекторов.
        monkeypatch.setitem(config.DETECTOR_TYPES, "regex",
                            config.DETECTOR_TYPES["regex"] - {"inn"})
        res = anonymize_detailed("ИНН 7707083893, IP 192.168.0.1", [regex], verify=False)
        assert "7707083893" in res.text
        assert "[ИНН]" not in res.text
        assert "[IP]" in res.text             # другой тип того же детектора маскируется

    def test_spans_found_unaffected(self, monkeypatch):
        # Конфиг гасит замену, но не обнаружение: спан всё равно посчитан.
        monkeypatch.setitem(config.DETECTOR_TYPES, "regex",
                            config.DETECTOR_TYPES["regex"] - {"inn"})
        res = anonymize_detailed("ИНН 7707083893", [regex], verify=False)
        assert res.spans_found["regex"] == 1
        assert "[ИНН]" not in res.text and "7707083893" in res.text

    def test_none_allows_all_types(self, monkeypatch):
        # None для детектора = разрешены все типы (поведение по умолчанию).
        monkeypatch.setitem(config.DETECTOR_TYPES, "regex", None)
        res = anonymize_detailed("ИНН 7707083893", [regex], verify=False)
        assert "[ИНН]" in res.text

    def test_verify_respects_detector_types(self, monkeypatch):
        # verify не должен добирать тип, запрещённый детектору llm. Мокаем LMStudio.
        monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "m")
        monkeypatch.setattr(llm, "_lmstudio_chat",
                            lambda system, text: '{"entities":[{"type":"локация","text":"Москва"}]}')
        monkeypatch.setitem(config.DETECTOR_TYPES, "llm",
                            config.DETECTOR_TYPES["llm"] - {"loc"})
        out = llm.verify_with_llm("город Москва", 1)
        assert "Москва" in out and "[Локация]" not in out

    def test_verify_masks_allowed_type(self, monkeypatch):
        # Явно разрешаем loc детектору llm → verify его добирает и маскирует.
        monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "m")
        monkeypatch.setattr(llm, "_lmstudio_chat",
                            lambda system, text: '{"entities":[{"type":"локация","text":"Москва"}]}')
        monkeypatch.setitem(config.DETECTOR_TYPES, "llm",
                            config.DETECTOR_TYPES["llm"] | {"loc"})
        out = llm.verify_with_llm("город Москва", 1)
        assert "[Локация]" in out and "Москва" not in out


# ===========================================================================
#  13. Финальная группировка меток (config.LABEL_GROUPS / relabel_groups)
# ===========================================================================

class TestLabelGroups:
    def test_config_keys_and_values_are_known_types(self):
        for src, dst in config.LABEL_GROUPS.items():
            assert src in config.LABELS and dst in config.LABELS

    def test_single_component_to_fio(self):
        assert relabel_groups("[Фамилия]") == "[ФИО]"
        assert relabel_groups("[Имя]") == "[ФИО]"
        assert relabel_groups("[Отчество]") == "[ФИО]"

    def test_loc_to_address(self):
        assert relabel_groups("[Локация]") == "[Адрес]"

    def test_other_labels_untouched(self):
        assert relabel_groups("[Организация] [Телефон]") == "[Организация] [Телефон]"

    def test_consecutive_components_collapse_to_one_fio(self):
        # Разбитое на части ФИО без пунктуации → один [ФИО] (relabel + collapse).
        out = collapse_repeated_labels(relabel_groups("[Фамилия] [Имя] [Отчество]"))
        assert out == "[ФИО]"

    def test_components_separated_by_punctuation_not_merged(self):
        # Разделённые запятой компоненты — это разные люди, не склеиваем.
        out = collapse_repeated_labels(relabel_groups("[Фамилия], [Имя]"))
        assert out == "[ФИО], [ФИО]"

    def test_identical_adjacent_merged_but_not_across_punctuation(self):
        assert collapse_repeated_labels("[Адрес] [Адрес]") == "[Адрес]"
        assert collapse_repeated_labels("[Адрес], [Адрес]") == "[Адрес], [Адрес]"

    @needs_natasha
    def test_pipeline_full_name_becomes_single_fio(self):
        res = anonymize_detailed("Иванов Иван Иванович", [natasha], verify=False)
        assert res.text == "[ФИО]"
