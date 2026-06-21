# -*- coding: utf-8 -*-
"""
Конфигурация анонимизатора: метки, приоритеты, регэкспы, настройки LMStudio.

Всё «крутибельное» собрано здесь, отдельно от логики — менять можно, не трогая
код детекторов и конвейера.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("anonymizer")

# Плоские метки замены. Двух разных людей обоих закрасит как [Имя] [Фамилия].
LABELS = {
    "name":       "[Имя]",
    "surname":    "[Фамилия]",
    "patronymic": "[Отчество]",
    "person":     "[ФИО]",          # персона, не разобранная на части
    "org":        "[Организация]",
    "loc":        "[Локация]",
    "address":    "[Адрес]",
    "email":      "[Email]",
    "phone":      "[Телефон]",
    "inn":        "[ИНН]",
    "snils":      "[СНИЛС]",
    "passport":   "[Паспорт]",
    "card":       "[БанковскаяКарта]",
    "ip":         "[IP]",
    "date":       "[Дата]",
    "money":      "[Сумма]",
}

# Финальная группировка меток: на самом последнем шаге конвейера тонкие типы
# сворачиваются в обобщающие (далее collapse_repeated_labels схлопывает соседние
# одинаковые метки в одну). Ключ → тип, в который переименовать.
# Компоненты ФИО → [ФИО]; локация → адрес. {} отключает группировку.
LABEL_GROUPS = {
    "name": "person",
    "surname": "person",
    "patronymic": "person",
    "loc": "address",
}

# Приоритет на пересечении спанов: больше число — важнее метка.
# Структурированные ID и компоненты имени важнее общих ORG/LOC/DATE.
PRIORITY = {
    "email": 100, "phone": 100, "card": 100, "ip": 100,
    "passport": 100, "snils": 100, "inn": 95,
    "surname": 90, "name": 90, "patronymic": 90,
    "address": 80,
    "person": 70,
    "money": 60,
    "org": 50,
    "loc": 40,
    "date": 30,
}

# --- Составные части шаблона денежной суммы ---------------------------------
# Число: либо группы по 3 цифры через разделитель тысяч (1 500 000 / 1.500.000),
# либо обычное число, в обоих случаях с опциональной дробной частью.
_MONEY_NUM = r"\d{1,3}(?:[\s.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
# Необязательный множитель суммы.
_MONEY_SCALE = r"(?:\s?(?:тыс|млн|млрд)\.?)?"
# Валюта: слово (с границей \b, чтобы не цеплять «рубильник») или символ.
_MONEY_CUR = (
    r"(?:руб(?:лей|ля|ль)?|коп(?:еек|ейки|ейка)?|долл(?:ар(?:ов|а)?)?"
    r"|евро|тенге|rub|kgs|cdf|aed|usd|eur|gbp)\b\.?|[₽$€£]"
)

# Жадные регулярные шаблоны (режим максимальной полноты).
REGEXES = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    # Телефон РФ, несколько форматов:
    "phone": re.compile(
        # 1) с префиксом +7 / 8 и любыми разделителями;
        r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}"
        # 2) без префикса, но С ОБЯЗАТЕЛЬНЫМИ разделителями (иначе совпал бы с голым
        #    10-значным ИНН): код 3–4 цифры (опц. в скобках) + номер 3-2-2,
        #    напр. "495 123-45-67", "(495) 123 45 67";
        r"|\(?\d{3,4}\)?[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}"
        # 3) 7-значный локальный номер без кода, напр. "123-45-67".
        r"|\b\d{3}[\s\-]\d{2}[\s\-]\d{2}\b"
    ),
    # Банковская карта: 16 цифр группами по 4 (разделители необязательны).
    "card": re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"),
    # СНИЛС: 123-456-789 00 (пробел или дефис перед контрольными 2 цифрами).
    "snils": re.compile(r"\b\d{3}-\d{3}-\d{3}[\s-]\d{2}\b"),
    # IPv4.
    "ip": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    # ВАЖНО: паспорт ОБЯЗАН требовать разделитель между серией и номером,
    # иначе шаблон совпадёт с «голым» 10-значным ИНН и число получит неверную метку.
    "passport": re.compile(r"\b\d{2}\s\d{2}\s\d{6}\b|\b\d{4}\s\d{6}\b"),
    # ИНН: 10 (юр.лицо) или 12 (физ.лицо) цифр подряд.
    "inn": re.compile(r"\b\d{10}\b|\b\d{12}\b"),
    # Сумма: ОБЯЗАТЕЛЬНО с валютой (символ/слово), иначе голые числа (ИНН/индексы)
    # стали бы суммами. Две формы: «число [множитель] валюта» и «символ число».
    "money": re.compile(
        rf"(?:{_MONEY_NUM}){_MONEY_SCALE}\s?(?:{_MONEY_CUR})"
        rf"|[₽$€£]\s?(?:{_MONEY_NUM})",
        re.IGNORECASE,
    ),
}

# Настройки LMStudio (OpenAI-совместимый локальный сервер).
LMSTUDIO = {
    "base_url": "http://localhost:1234/v1",
    "model": None,            # None → автоопределение через GET /v1/models
    "timeout": 120,           # секунд на запрос
    "temperature": 0,         # детерминированный вывод
    "max_tokens": 2000,       # ограничивает длину ответа (защита от «болтливых» reasoning-моделей)
    "max_verify_passes": 2,   # сколько раз доп. проверять закрашенный текст
}

# Структурированные ID, которые мы НЕ берём из ответа LLM: их детерминированно и
# точно находят regex и Presidio, а LLM на них регулярно ошибается (путает СНИЛС с
# телефоном, ИНН с паспортом и т.п.). Роль LLM — контекстный добор смысловых
# сущностей (имена, организации, локации, адреса, даты, суммы).
LLM_SKIP_TYPES = {"email", "phone", "card", "ip", "passport", "snils", "inn"}

# --- Какие типы ПДн обезличивать -------------------------------------------
# Переключатель на каждый тип спана: True — маскировать, False — оставить как есть.
# Управляет только заменой в тексте; на обнаружение (spans_found) не влияет.
ANONYMIZE_NAME = True
ANONYMIZE_SURNAME = True
ANONYMIZE_PATRONYMIC = True
ANONYMIZE_PERSON = True
ANONYMIZE_ORG = True
ANONYMIZE_LOC = True
ANONYMIZE_ADDRESS = True
ANONYMIZE_EMAIL = True
ANONYMIZE_PHONE = True
ANONYMIZE_INN = True
ANONYMIZE_SNILS = True
ANONYMIZE_PASSPORT = True
ANONYMIZE_CARD = True
ANONYMIZE_IP = True
ANONYMIZE_DATE = False
ANONYMIZE_MONEY = False

# Сводный словарь тип → флаг (правьте константы выше; ключи совпадают с LABELS).
ANONYMIZE_TYPES = {
    "name": ANONYMIZE_NAME, "surname": ANONYMIZE_SURNAME,
    "patronymic": ANONYMIZE_PATRONYMIC, "person": ANONYMIZE_PERSON,
    "org": ANONYMIZE_ORG, "loc": ANONYMIZE_LOC, "address": ANONYMIZE_ADDRESS,
    "email": ANONYMIZE_EMAIL, "phone": ANONYMIZE_PHONE, "inn": ANONYMIZE_INN,
    "snils": ANONYMIZE_SNILS, "passport": ANONYMIZE_PASSPORT,
    "card": ANONYMIZE_CARD, "ip": ANONYMIZE_IP, "date": ANONYMIZE_DATE,
    "money": ANONYMIZE_MONEY,
}


def is_type_enabled(t: str) -> bool:
    """Нужно ли маскировать тип t. Неизвестный тип считаем включённым (безопаснее)."""
    return ANONYMIZE_TYPES.get(t, True)


# --- Какие детекторы запускать ----------------------------------------------
# Переключатель на каждый детектор: True — участвует в наборе по умолчанию,
# False — пропускается. Действует только на запуск без явного списка детекторов
# (полный ансамбль: anonymize(text), POST /anonymize); явный список — как у
# /anonymize/{detector} и eval-скриптов — выполняется как передан (диагностика).
# DETECTOR_LLM = False отключает и финальную LLM-проверку (verify).
DETECTOR_REGEX = True
DETECTOR_NATASHA = True
DETECTOR_PRESIDIO = True
DETECTOR_LLM = True

# Сводный словарь имя → флаг (правьте константы выше; ключи — NAME детекторов).
DETECTORS_ENABLED = {
    "regex": DETECTOR_REGEX,
    "natasha": DETECTOR_NATASHA,
    "presidio": DETECTOR_PRESIDIO,
    "llm": DETECTOR_LLM,
}


def is_detector_enabled(name: str) -> bool:
    """Запускать ли детектор name. Неизвестное имя считаем включённым (безопаснее)."""
    return DETECTORS_ENABLED.get(name, True)


# --- Какие типы каждый детектор имеет право ЗАМЕНЯТЬ -------------------------
# Детектор может НАЙТИ что угодно, но в финальную замену попадают только спаны
# тех типов, что перечислены для его источника. Тесты показали: часть типов точнее
# ловит regex, часть — Natasha; некоторые детекторы дают ложные срабатывания на
# отдельных типах — здесь их можно отсечь, не выключая детектор целиком.
# Фильтр применяется ПОСЛЕ разбора персон (split_persons) и ДО слияния, поэтому
# ключи — финальные типы (name/surname/patronymic вместо person; person оставлен
# как fallback, если разбор персоны не удался). На обнаружение (spans_found) не влияет.
# По умолчанию у каждого детектора перечислен его «родной» набор — это no-op;
# чтобы запретить тип, уберите его из набора. None = разрешены все типы.
DETECTOR_REGEX_TYPES = {"email", "phone", "card", "snils", "ip", "passport", "inn", "money"}
DETECTOR_NATASHA_TYPES = {"name", "surname", "patronymic", "person", "org", "loc", "address", "date", "money"}
DETECTOR_PRESIDIO_TYPES = {"name", "surname", "patronymic", "person", "card", "ip", "date", "inn", "snils", "passport"}
DETECTOR_LLM_TYPES = {"name", "surname", "patronymic", "person", "date", "money"}

# Сводный словарь имя детектора → набор разрешённых типов (правьте константы выше).
DETECTOR_TYPES = {
    "regex": DETECTOR_REGEX_TYPES,
    "natasha": DETECTOR_NATASHA_TYPES,
    "presidio": DETECTOR_PRESIDIO_TYPES,
    "llm": DETECTOR_LLM_TYPES,
}


def is_detector_type_enabled(name: str, t: str) -> bool:
    """Имеет ли детектор name право ЗАМЕНЯТЬ тип t. Неизвестный детектор/None → всё (безопаснее)."""
    allowed = DETECTOR_TYPES.get(name)
    if allowed is None:
        return True
    return t in allowed


# Настройки HTTP-API (FastAPI). Хост/порт/ключ можно переопределить переменными
# окружения ANONYMIZER_HOST / ANONYMIZER_PORT / ANONYMIZER_API_KEY (см. api.py).
API = {
    # Только локальный доступ. Сервис принимает НЕобезличенный текст по открытому
    # HTTP, поэтому 0.0.0.0 (доступ извне) — только осознанно и только за
    # reverse-proxy с TLS.
    "host": "127.0.0.1",
    "port": 8077,
    "api_key": "change-me",   # дефолт небезопасен — задайте свой через env/конфиг
    # Максимальная длина текста в /anonymize (символов): защита от DoS — запросы
    # сериализуются глобальным локом, один гигантский текст заблокировал бы всех.
    "max_text_chars": 100_000,
}
