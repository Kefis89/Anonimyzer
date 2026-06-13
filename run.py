# -*- coding: utf-8 -*-
"""
Запуск HTTP-сервера анонимайзера.

    .venv\\Scripts\\python.exe run.py

Слушает 127.0.0.1:8077 по умолчанию. Хост/порт/ключ переопределяются переменными
окружения ANONYMIZER_HOST / ANONYMIZER_PORT / ANONYMIZER_API_KEY (читаются из .env,
если установлен python-dotenv). Подробности и эндпоинты — в anonymizer/api.py.
"""

from __future__ import annotations

import logging

from anonymizer.api import serve

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    serve()
