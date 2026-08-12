# Развёртывание на небольшом VPS

Обновлено: 2026-08-12

## Рекомендуемая конфигурация

- Ubuntu 24.04 LTS;
- 1 vCPU;
- 2 ГБ RAM;
- 20 ГБ SSD/NVMe;
- дата-центр в России для первого контура HH.ru;
- публичный IPv4 и SSH-доступ.

Этого достаточно для текущего Python-процесса. Система запускается один раз в день и не требует постоянно работающего web-сервера.

## Что будет происходить

Systemd запускает одноразовый Docker-контейнер ежедневно в 09:00 по московскому времени. Добавлена случайная задержка до пяти минут, чтобы запросы не начинались всегда в одну секунду.

Результаты сохраняются в `/opt/searchorders/output`:

- `leads-YYYY-MM-DDTHH-MM.json` — результат отдельного запуска;
- `latest.json` — ссылка на последний успешный результат.

Пропущенный из-за перезагрузки запуск выполняется после включения сервера.

## Подготовка сервера

1. Создать VPS с Ubuntu 24.04 LTS.
2. Подключиться к нему по SSH.
3. Установить Docker Engine и Docker Compose plugin по официальной инструкции Docker для Ubuntu.
4. Клонировать репозиторий в фиксированный каталог:

```bash
sudo git clone https://github.com/famesel7-coder/searchorders.git /opt/searchorders
cd /opt/searchorders
sudo git checkout agent/initial-system-profile
```

После слияния draft PR отдельная команда `checkout` не понадобится: развёртывать нужно будет ветку `main`.

## Конфигурация и сборка

```bash
cd /opt/searchorders
sudo cp .env.example .env
sudo docker compose build
```

В `.env` рекомендуется заменить `HH_USER_AGENT` на строку с рабочим адресом для связи. Секреты не нужно коммитить: `.env` исключён из Git.

## Ручная проверка

```bash
cd /opt/searchorders
sudo ./deploy/run-daily.sh
ls -la output
```

Первый запуск является проверкой доступности HH.ru с IP выбранного VPS. Если источник вернёт HTTP 403, нужно сменить регион/IP сервера или использовать другой разрешённый источник; обход защиты сайта в систему не закладывается.

## Включение расписания

```bash
cd /opt/searchorders
sudo ./deploy/install-systemd.sh
```

Проверка:

```bash
systemctl status search-orders.timer
systemctl list-timers search-orders.timer
journalctl -u search-orders.service -n 100 --no-pager
```

Ручной запуск через systemd:

```bash
sudo systemctl start search-orders.service
```

## Изменение времени

Изменить `OnCalendar` в `deploy/search-orders.timer`, затем повторно установить units:

```bash
sudo ./deploy/install-systemd.sh
```

Часовой пояс указывается непосредственно в расписании, поэтому сервер может оставаться в UTC.

## Обновление приложения

```bash
cd /opt/searchorders
sudo git pull --ff-only
sudo docker compose build
sudo systemctl start search-orders.service
```

Перед обновлением нужно убедиться, что рабочая ветка соответствует актуальному PR или `main`.

