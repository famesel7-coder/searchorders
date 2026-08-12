# Развёртывание Telegram-бота на VPS

Обновлено: 2026-08-12

## Рекомендуемая конфигурация

- Ubuntu 24.04 LTS;
- 1 vCPU;
- 2 ГБ RAM;
- 20 ГБ SSD/NVMe;
- публичный IPv4 и SSH-доступ.

Московское время задаётся внутри контейнера независимо от региона сервера. Поиск запускается только по кнопке; cron и ежедневный timer отсутствуют.

## Что работает на сервере

Постоянно запущен один небольшой Telegram-бот. После нажатия «Запустить поиск» он:

1. проверяет публичные тендеры Workspace;
2. удаляет уже показанные заказы через SQLite;
3. фильтрует штатные и неподходящие задачи;
4. оценивает релевантность;
5. подбирает кейс I’MON;
6. возвращает карточки и черновики предложений в разрешённый Telegram-чат.

Бот не отправляет сообщения заказчикам и не подаёт заявки на площадке.

## Подготовка сервера

1. Подключиться к Ubuntu по SSH или открыть консоль провайдера.
2. Установить Git, Docker Engine и Docker Compose plugin.
3. Клонировать рабочую ветку:

```bash
sudo git clone https://github.com/famesel7-coder/searchorders.git /opt/searchorders
cd /opt/searchorders
sudo git checkout agent/initial-system-profile
```

После слияния draft PR развёртывать нужно будет ветку `main`.

## Создание Telegram-бота

1. Создать бота через официальный `@BotFather`.
2. Скопировать `.env.example`:

```bash
cd /opt/searchorders
sudo cp .env.example .env
sudo nano .env
```

3. Вставить токен только в `TELEGRAM_BOT_TOKEN`. `TELEGRAM_CHAT_ID` сначала оставить пустым.
4. Собрать и запустить контейнер:

```bash
sudo docker compose build
sudo docker compose up -d
sudo docker compose logs --tail=100 search-orders
```

5. Написать созданному боту `/start`. Он вернёт текущий `TELEGRAM_CHAT_ID`, но не позволит запускать поиск.
6. Добавить полученный ID в `/opt/searchorders/.env` и перезапустить:

```bash
sudo docker compose up -d --force-recreate
```

После этого бот отвечает только настроенному чату. Токен и `.env` нельзя добавлять в Git или пересылать в чат поддержки.

## Проверка

```bash
cd /opt/searchorders
sudo docker compose ps
sudo docker compose logs --tail=100 search-orders
```

В Telegram отправить `/start` и нажать «Запустить поиск». Первый live-запуск одновременно проверяет доступность публичных страниц Workspace с IP VPS.

Если источник запрещён в `robots.txt` или возвращает ошибку доступа, система покажет предупреждение и не пытается обходить ограничение.

## Ручной диагностический запуск

Чтобы не записывать тестовые данные в основную базу повторов:

```bash
sudo docker compose run --rm search-orders scan \
  --max-results 5 \
  --state /tmp/smoke.db \
  --output /app/output/smoke.json
```

## Хранилище

- `/opt/searchorders/state/searchorders.db` — уже показанные заказы;
- `/opt/searchorders/output/leads.json` — последняя JSON-выгрузка команды `scan`;
- Docker volume mapping сохраняет оба каталога между перезапусками контейнера.

## Обновление

```bash
cd /opt/searchorders
sudo git pull --ff-only
sudo docker compose build
sudo docker compose up -d --force-recreate
```

