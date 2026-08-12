# Запуск ядра MVP

Обновлено: 2026-08-12

## Что уже работает

По кнопке или команде `scan` система получает свежие публичные тендеры Workspace, затем:

1. находит сигналы проектной и штатной работы;
2. определяет услуги и отрасль;
3. исключает штатные вакансии;
4. считает релевантность I’MON;
5. выбирает кейс с прямой ссылкой;
6. формирует черновик ответа;
7. сортирует лиды по очередям hot, review, archive и rejected.

HH.ru исключён. Первый коннектор использует публичные страницы Workspace, проверяет правила `robots.txt` и ограничивает частоту запросов.

## Установка

Требуется Python 3.11 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Тесты

```bash
python -m unittest discover -s tests -v
```

Тестовый прогон использует четыре примера: premium real estate web-проект, штатную UX/UI-вакансию, backend-вакансию и проект презентации для автомобильной конференции.

## Проверка ядра

```bash
search-orders evaluate tests/fixtures/sample_leads.json \
  --output output/sample-results.json
```

## Немедленный поиск

```bash
search-orders scan \
  --sources data/sources.yaml \
  --state state/searchorders.db \
  --max-results 30 \
  --output output/leads.json
```

SQLite хранит уже показанные заказы. Повторный запуск не возвращает один и тот же `source + external_id` снова.

## Telegram-кнопка

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
search-orders bot
```

Бот принимает `/start`, `/search` и callback кнопки «Запустить поиск». Запросы из других чатов игнорируются. Если `TELEGRAM_CHAT_ID` пока пуст, команда `/start` возвращает ID текущего чата для первоначальной настройки, но поиск не запускает.

## Формат результата

Верхний уровень JSON:

- `generated_at`;
- `summary` с количеством лидов по очередям;
- `items` — отсортированные результаты.

Каждый результат содержит исходную карточку лида, решение фильтра, общий балл и разбивку, выбранный кейс и черновик предложения.

## Следующие этапы

1. Выполнить live smoke-test Workspace с IP VPS.
2. Исследовать компанию только для hot/review лидов.
3. Заменить базовый черновик на ИИ-персонализацию.
4. Подключить второй российский источник и источники США/Европы.
5. Добавить кнопки обратной связи для калибровки скоринга.
