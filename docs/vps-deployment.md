# Развёртывание на небольшом VPS

Обновлено: 2026-08-12

## Рекомендуемая конфигурация

- Ubuntu 24.04 LTS;
- 1 vCPU;
- 2 ГБ RAM;
- 20 ГБ SSD/NVMe;
- публичный IPv4 и SSH-доступ.

Регион VPS больше не привязан к HH.ru. Его нужно выбрать после smoke-тестов первых проектных источников; московское время задаётся внутри приложения независимо от региона сервера.

## Модель запуска

Ежедневное расписание отключено. VPS будет держать кнопочный интерфейс и коннекторы в готовности, а полный поиск начнётся после команды пользователя.

Пока кнопочный интерфейс не подключён, Docker-образ используется для проверки ядра и будущих коннекторов. Автоматическая отправка предложений выключена.

## Подготовка сервера

1. Создать VPS с Ubuntu 24.04 LTS.
2. Подключиться по SSH.
3. Установить Docker Engine и Docker Compose plugin по официальной инструкции Docker для Ubuntu.
4. Клонировать репозиторий:

```bash
sudo git clone https://github.com/famesel7-coder/searchorders.git /opt/searchorders
cd /opt/searchorders
sudo git checkout agent/initial-system-profile
```

После слияния draft PR развёртывать нужно будет ветку `main`.

## Конфигурация и сборка

```bash
cd /opt/searchorders
sudo cp .env.example .env
sudo docker compose build
```

Секреты будущего Telegram-интерфейса и ИИ хранятся только в `/opt/searchorders/.env`; файл исключён из Git.

## Проверка ядра в контейнере

```bash
cd /opt/searchorders
sudo docker compose run --rm \
  -v "$(pwd)/tests:/app/tests:ro" \
  search-orders evaluate tests/fixtures/sample_leads.json \
  --output /app/output/sample-results.json
```

Результат появится в `/opt/searchorders/output/sample-results.json`.

## Обновление

```bash
cd /opt/searchorders
sudo git pull --ff-only
sudo docker compose build
```

Постоянный `docker compose up -d` будет включён после добавления кнопочного Telegram-интерфейса.

