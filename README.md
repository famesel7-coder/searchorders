# Search Orders

Search Orders — внутренний каталог проектного спроса для I’MON Digital Agency. Система читает публичные Telegram-каналы, выбранные Telegram-чаты через MTProto, VK-сообщества и community/RSS-ленты, нормализует публикации, удаляет репосты, отделяет проектный спрос от вакансий и резюме, оценивает релевантность и сохраняет всё в постоянный каталог.

## Жёсткая граница продукта

Биржи, тендерные площадки и job boards не являются источниками Search Orders. Типы `workspace`, `freelance_task`, `marketplace` и `project_marketplace` запрещены валидатором конфигурации.

## Pipeline

1. Каждый источник сканируется независимо со своим лимитом — первый источник больше не может «съесть» общий лимит.
2. Все сообщения сохраняются как raw posts в SQLite.
3. Из текста извлекаются контакты и бюджет.
4. Репосты группируются по fingerprint, similarity и совпадающим контактам.
5. Классификатор различает `project_demand`, `employment`, `self_promo`, `demand`, `ambiguous`.
6. Затем применяются service match, scoring и case matching.
7. Canonical lead сохраняется в каталоге и связывается со всеми исходными публикациями.
8. Повторный scan не теряет данные и не создаёт тот же lead заново.

## Быстрый старт

```bash
cp .env.example .env
# Для публичного web обязательно задайте WEB_AUTH_TOKEN.
docker compose up -d --build search-orders
```

Открыть каталог: `http://<host>:8080/`. При включённом `WEB_AUTH_TOKEN` браузер запросит Basic Auth: имя пользователя любое, пароль — значение токена.

```bash
docker compose run --rm search-orders scan --max-results 30
docker compose run --rm search-orders catalog --limit 200
docker compose run --rm search-orders sources-status
```

## Источники

`data/sources.yaml` содержит seed registry без бирж. Public Telegram работает без Telegram API credentials. `telegram_client` требует `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`. `vk_wall` требует `VK_ACCESS_TOKEN` и включается после добавления проверенных публичных VK-групп.

## Хранилище

`state/searchorders.db` — БД приложения: `scan_runs`, `sources`, `posts`, `leads`, `lead_posts`, `lead_status_history`. Статусы каталога: `new`, `interesting`, `review`, `rejected`, `contacted`, `replied`, `meeting`, `won`, `lost`, `ignored`.

## Web API

- `GET /catalog.json` — persistent catalog;
- `GET /results.json` — совместимый alias;
- `GET /sources.json` — health источников;
- `GET /status.json` — состояние scan;
- `POST /scan` — запускает scan в background thread и возвращает HTTP 202;
- `GET /healthz` — healthcheck без авторизации.

## Telegram на VPS

Если MTProto недоступен у провайдера, `telegram_client` можно оставить выключенным и использовать `telegram_public` с IPv4 fallback. Для полного MTProto-покрытия worker лучше запускать на хосте, где Telegram DC доступны.

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src tests
```
