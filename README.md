# Search Orders

Search Orders — внутренний каталог проектного спроса для I’MON Digital Agency. Система читает публичные Telegram-каналы, выбранные Telegram-чаты через MTProto, VK-сообщества и community/RSS-ленты, нормализует публикации, удаляет репосты, отделяет проектный спрос от вакансий и резюме, оценивает релевантность и сохраняет всё в постоянный каталог.

## Жёсткая граница продукта

Биржи, тендерные площадки и job boards не являются источниками Search Orders. Типы `workspace`, `freelance_task`, `marketplace` и `project_marketplace` запрещены валидатором конфигурации.

## Pipeline

1. Каждый источник сканируется независимо со своим лимитом — первый источник больше не может «съесть» общий лимит.
2. Все сообщения сохраняются как raw posts в SQLite.
3. Из текста извлекаются контакты, бюджет, срок и явно указанное имя заказчика/бренда.
4. Репосты группируются по fingerprint, similarity и совпадающим контактам.
5. Базовый классификатор различает `project_demand`, `employment`, `self_promo`, `demand`, `ambiguous`.
6. Опционально неоднозначные посты можно уточнять семантическим Structured Output-классификатором; при его недоступности pipeline автоматически остаётся на правилах.
7. Затем применяются service match, scoring и case matching.
8. Canonical lead сохраняется в каталоге и связывается со всеми исходными публикациями.
9. Пользовательский статус (`interesting`, `contacted`, `won` и т.д.) сохраняется как feedback history.

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
docker compose run --rm search-orders feedback-status 42 contacted
```

## Источники

`data/sources.yaml` содержит seed registry без бирж. Public Telegram работает без Telegram API credentials. `telegram_client` требует `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`. `vk_wall` требует `VK_ACCESS_TOKEN` и включается после добавления проверенных публичных VK-групп.

## Опциональный semantic classifier

По умолчанию он выключен. Для включения задайте одновременно:

```dotenv
OPENAI_CLASSIFIER_ENABLED=1
OPENAI_CLASSIFIER_MODEL=<выбранная модель>
OPENAI_API_KEY=<server-side key>
```

Текст публичного поста отправляется как недоверенные данные; Structured Output используется только для intent/service/company/deadline refinement. Ошибка или отсутствие API не ломает scan.

## Хранилище и feedback

`state/searchorders.db` — БД приложения: `scan_runs`, `sources`, `posts`, `leads`, `lead_posts`, `lead_status_history`. Статусы: `new`, `interesting`, `review`, `rejected`, `contacted`, `replied`, `meeting`, `won`, `lost`, `ignored`. Их можно менять прямо в web-карточке.

## Web API

- `GET /catalog.json` — persistent catalog;
- `GET /results.json` — совместимый alias;
- `GET /sources.json` — health источников;
- `GET /feedback.json` — распределение CRM/feedback-статусов;
- `GET /status.json` — состояние scan;
- `POST /scan` — запускает scan в background thread и возвращает HTTP 202;
- `POST /leads/<id>/status` — меняет feedback status;
- `GET /healthz` — healthcheck без авторизации.

## Telegram на VPS

Если MTProto недоступен у провайдера, `telegram_client` можно оставить выключенным и использовать `telegram_public` с IPv4 fallback. Для полного MTProto-покрытия worker лучше запускать на хосте, где Telegram DC доступны.

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src tests
```
