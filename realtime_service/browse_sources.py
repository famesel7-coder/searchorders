"""Browser-only job searches and safe manual platform application sources.

These are links, not connectors: no scraping, requests, API keys or automatic
availability claims. Users open the original site and reply using their account.
"""
import re
from urllib.parse import urlparse, urlencode

PLATFORMS = (
    {"id": "hh", "name": "HeadHunter", "host": "hh.ru",
     "description": "Проектные вакансии, отклик из профиля кандидата"},
    {"id": "fl", "name": "FL.ru", "host": "fl.ru",
     "description": "Биржа заказов, доступность бесплатного отклика проверяйте в карточке"},
    {"id": "kwork", "name": "Kwork", "host": "kwork.ru",
     "description": "Проекты покупателей, отклик из аккаунта исполнителя"},
    {"id": "freelance", "name": "Freelance.ru", "host": "freelance.ru",
     "description": "Задания, фильтр «Доступно всем», без Premium"},
)

def hh_search(query):
    return "https://hh.ru/search/vacancy?" + urlencode({
        "text": query,
        "employment_form": "PROJECT",
        "work_format": "REMOTE",
        "order_by": "publication_time",
    })

SEARCHES = (
    {"site": "HeadHunter", "category": "web", "title": "Сайты и Tilda", "url": hh_search("Tilda дизайнер")},
    {"site": "HeadHunter", "category": "uiux", "title": "UI/UX и интерфейсы", "url": hh_search("UI UX дизайнер")},
    {"site": "HeadHunter", "category": "presentations", "title": "Презентации", "url": hh_search("дизайнер презентаций")},
    {"site": "HeadHunter", "category": "branding", "title": "Графический дизайн", "url": hh_search("графический дизайнер")},
    {"site": "FL.ru", "category": "web", "title": "Дизайн сайтов", "url": "https://www.fl.ru/projects/category/saity/web-dizajner-razrabotka-sajtov/"},
    {"site": "FL.ru", "category": "uiux", "title": "UI/UX", "url": "https://www.fl.ru/projects/category/dizajn/ui-ux-dizajn/"},
    {"site": "FL.ru", "category": "branding", "title": "Все дизайн-заказы", "url": "https://www.fl.ru/projects/"},
    {"site": "Kwork", "category": "all", "title": "Биржа проектов", "url": "https://kwork.ru/projects"},
    {"site": "Freelance.ru", "category": "all", "title": "Задания · доступно всем", "url": "https://freelance.ru/task"},
)

# Strict per-platform source URLs; search results and profile pages are not
# individual project cards and cannot be added as project leads.
PATHS = {
    "hh.ru": re.compile(r"^/vacancy/\d{5,15}/?$"),
    "fl.ru": re.compile(r"^/projects/\d{4,12}(?:/[^/?#]+)?/?$"),
    "kwork.ru": re.compile(r"^/projects/\d{4,15}(?:/[^?#]*)?$"),
    "freelance.ru": re.compile(r"^/task/view/\d{1,15}/?$"),
}

def platform_for_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return None
        pattern = PATHS.get(host)
        if pattern and pattern.fullmatch(parsed.path):
            return next((p for p in PLATFORMS if p["host"] == host), None)
    except ValueError:
        pass
    return None
