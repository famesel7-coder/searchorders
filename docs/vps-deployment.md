# VPS deployment

Обновлено: 2026-08-17.

На VPS работает web-каталог и, при наличии токена, Telegram-бот. Сканирование читает только social/community sources; биржи и job boards запрещены.

Создайте `/opt/searchorders/.env` из `.env.example`. Для публичного web нужен `WEB_AUTH_TOKEN`; текущий deploy workflow генерирует его автоматически, если поле пустое. Имя пользователя Basic Auth может быть любым, пароль — значение токена.

Опционально: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`; `VK_ACCESS_TOKEN`.

```bash
sudo git clone https://github.com/famesel7-coder/searchorders.git /opt/searchorders
cd /opt/searchorders
sudo git checkout agent/initial-system-profile
sudo cp .env.example .env
sudo docker compose up -d --build search-orders
```

Проверка:

```bash
curl -fsS http://127.0.0.1:8080/healthz
sudo docker compose ps
sudo docker compose logs --tail=100 search-orders
sudo docker compose run --rm search-orders scan --max-results 30
sudo docker compose run --rm search-orders sources-status
```

Основная БД — `/opt/searchorders/state/searchorders.db`. JSON в `output/` — только совместимая выгрузка последнего запуска. Если провайдер блокирует MTProto, используйте `telegram_public` или отдельный MTProto-worker на другом хосте.
