# -*- coding: utf-8 -*-
"""
Пример обращения к сервису анонимайзера из сторонней программы.

Используется только стандартная библиотека Python — никаких зависимостей,
скопировать можно в любой проект.

Запуск:
    python client_example.py "Иван Петров, ИНН 7707083893"
    python client_example.py                      # текст по умолчанию

Настройка через переменные окружения:
    ANONYMIZER_URL       адрес сервиса (по умолчанию http://localhost:8077)
    ANONYMIZER_API_KEY   ключ X-API-Key (по умолчанию change-me)

Для обращения с другой машины замените localhost на IP/хост сервера.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("ANONYMIZER_URL", "http://localhost:8077").rstrip("/")
API_KEY = os.environ.get("ANONYMIZER_API_KEY", "change-me")


def anonymize(text: str) -> dict:
    """
    Отправить текст сервису и получить {'text': ..., 'spans_found': {...}}.
    Бросает urllib.error.HTTPError при 4xx/5xx (например, 401 — неверный ключ).
    """
    req = urllib.request.Request(
        BASE_URL + "/anonymize",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def health() -> dict:
    """Статус сервиса и активные детекторы (ключ не требуется)."""
    with urllib.request.urlopen(BASE_URL + "/health", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else (
        """РАСПИСКА

в получении денежных средств

г. Москва
15 мая 2026 года

Я, Иванов Артём Сергеевич, 14 марта 1987 года рождения, паспорт 45 18 № 736492, выдан Отделом МВД России по району Сокольники г. Москвы 22 июня 2018 года, код подразделения 770-045, зарегистрированный по адресу: г. Москва, ул. Русаковская, д. 18, кв. 42, настоящей распиской подтверждаю, что получил от Петровой Марии Андреевны, 9 сентября 1990 года рождения, паспорт 45 20 № 918374, выдан ГУ МВД России по г. Москве 11 февраля 2020 года, код подразделения 770-112, зарегистрированной по адресу: г. Москва, Ленинградский проспект, д. 64, кв. 117, денежные средства в размере:

350 000 рублей 00 копеек
триста пятьдесят тысяч рублей 00 копеек.

Указанные денежные средства получены мной наличными денежными средствами в полном объёме в день подписания настоящей расписки.

Денежные средства переданы мне в качестве займа. Обязуюсь вернуть полученную сумму займа Петровой Марии Андреевне не позднее 15 ноября 2026 года.

Заем является беспроцентным. Дополнительных условий, комиссий и иных платежей стороны не установили.

Факт получения денежных средств подтверждаю. Претензий к Петровой Марии Андреевне по сумме, порядку и факту передачи денежных средств не имею.

Настоящая расписка составлена мной добровольно, в здравом уме и твердой памяти, без принуждения, обмана или угроз.

Подпись заемщика: Иванов А.С. /Иванов Артём Сергеевич/"""
    )
    try:
        print("health:", json.dumps(health(), ensure_ascii=False))
        result = anonymize(text)
        print("\nДО:    ", text)
        print("ПОСЛЕ: ", result["text"])
        print("детекторы:", json.dumps(result["spans_found"], ensure_ascii=False))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        print(f"Не удалось подключиться к {BASE_URL}: {e.reason}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # корректная кириллица в консоли Windows
    except Exception:
        pass
    main()
