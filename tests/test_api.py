# -*- coding: utf-8 -*-
"""
Тесты HTTP-API (anonymizer.api).

Запуск:  python -m pytest -v
Нужны fastapi и httpx (для TestClient); без них модуль целиком пропускается.
LMStudio/модели глушим monkeypatch'ем → детерминированный regex-only режим.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from anonymizer import api
from anonymizer.detectors import llm, natasha, presidio

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(api, "API_KEY", "test-key")
    # Детерминизм: отключаем модели и LMStudio → работает только regex.
    monkeypatch.setattr(natasha, "NATASHA", None)
    monkeypatch.setattr(presidio, "PRESIDIO", None)
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", None)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["detectors"]) == {"natasha", "presidio", "llm"}


def test_anonymize_requires_key():
    r = client.post("/anonymize", json={"text": "ИНН 7707083893"})
    assert r.status_code == 401


def test_anonymize_wrong_key():
    r = client.post("/anonymize", json={"text": "x"}, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_anonymize_ok():
    r = client.post("/anonymize",
                    json={"text": "ИНН 7707083893, IP 192.168.0.1"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "[ИНН]" in body["text"] and "[IP]" in body["text"]
    assert "7707083893" not in body["text"]
    assert set(body["spans_found"]) == {"regex", "natasha", "presidio", "llm"}


def test_reload_requires_key():
    assert client.post("/reload").status_code == 401


def test_anonymize_text_too_long():
    from anonymizer.config import API as api_config
    too_long = "x" * (api_config["max_text_chars"] + 1)
    r = client.post("/anonymize", json={"text": too_long},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 422


# --- пер-детекторные эндпоинты /anonymize/{detector} ---------------------------

def test_anonymize_one_regex():
    r = client.post("/anonymize/regex",
                    json={"text": "ИНН 7707083893, IP 192.168.0.1"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "[ИНН]" in body["text"] and "[IP]" in body["text"]
    assert "7707083893" not in body["text"]
    # spans_found содержит ровно один ключ — выбранный детектор.
    assert body["spans_found"] == {"regex": 2}


def test_anonymize_one_isolated():
    # natasha выключена фикстурой → её эндпоинт ничего не находит и не запускает
    # regex (изоляция): текст остаётся как есть, в spans_found только natasha.
    r = client.post("/anonymize/natasha",
                    json={"text": "ИНН 7707083893"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["spans_found"] == {"natasha": 0}
    assert body["text"] == "ИНН 7707083893"


def test_anonymize_one_requires_key():
    r = client.post("/anonymize/regex", json={"text": "x"})
    assert r.status_code == 401


def test_anonymize_one_unknown_detector():
    r = client.post("/anonymize/unknown",
                    json={"text": "x"}, headers={"X-API-Key": "test-key"})
    assert r.status_code == 422
