"""Create editable, task-specific outreach drafts without sending messages.

This deterministic generator is intentionally local, with no external API,
credentials, fabricated client names, portfolio achievements, or auto-send.
"""
import re
from typing import Mapping, Any

PORTFOLIO = "https://samsel.site"


def mentioned(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def short_brand(lead: Mapping[str, Any]) -> str:
    buyer = str(lead.get("buyer") or "").strip()
    if 2 <= len(buyer) <= 48 and not mentioned(
        buyer, r"^запрос", r"^дизайн", r"^ищ", r"^нуж", r"^для ", r"^на "
    ):
        return buyer
    body = str(lead.get("body") or "")
    # "Waistline (российский бренд женской одежды) ...".
    match = re.search(
        r"\b([A-Z][A-Za-z0-9-]{2,32})\s*\([^)]{0,65}\b(?:бренд|компания|студия)\b",
        body, re.I,
    )
    return match.group(1) if match else ""


def create_draft(lead: Mapping[str, Any]) -> str:
    body = str(lead.get("body") or "")[:3600]
    cat = str(lead.get("category") or "")
    brand = short_brand(lead)
    intro = ""
    detail = ""
    evidence = ""
    next_step = ""

    # Prioritise the concrete deliverable over a broad category assigned by
    # a keyword classifier. Marketplace infographics often contain "slides".
    if mentioned(body, r"wildberries|\bwb\b|\bozon\b|маркетплейс|карточ(?:ек|ки) товар"):
        intro = "ваш запрос по визуалам для маркетплейсов"
        if brand:
            intro += f" бренда {brand}"
        detail = ("Могу помочь с обложками и слайдами карточек: выделить преимущества товаров, "
                  "собрать понятную инфографику и выдержать единый визуальный стиль.")
        evidence = ("В моём портфолио есть инфографика и коммерческие визуальные материалы "
                    "для крупных брендов, включая Avito.")
        next_step = "Готов посмотреть текущие карточки и обсудить объём задач, сроки и стоимость."

    elif mentioned(body, r"упаковк|этикетк|коробк|пакетир"):
        intro = "ваш проект по дизайну упаковки"
        detail = ("Могу проработать визуальную концепцию, композицию и типографику, "
                  "а затем подготовить макеты под необходимые форматы.")
        evidence = ("Занимаюсь айдентикой и графическим дизайном, "
                    "работал над визуальными материалами для крупных брендов.")
        next_step = "Готов ознакомиться с продуктом, техническими требованиями и референсами."

    elif mentioned(body, r"брендбук|айдентик|фирменн.{0,15}стил|ребрендинг|логотип"):
        intro = "ваш запрос по фирменному стилю"
        if brand:
            intro += f" для {brand}"
        detail = ("Могу помочь с визуальной концепцией, типографикой и системой носителей, "
                  "чтобы фирменный стиль последовательно работал в разных форматах.")
        evidence = ("В портфолио представлены проекты по брендингу и визуальным коммуникациям, "
                    "в том числе для Haval.")
        next_step = "Могу изучить текущие материалы и предложить подход к задаче и этапам работы."

    elif cat == "web" or mentioned(body, r"\btilda\b|тильд|\bwebflow\b|\bframer\b|wordpress|лендинг"):
        platform = (
            "Tilda" if mentioned(body, r"tilda|тильд") else
            "Webflow" if mentioned(body, r"webflow") else
            "Framer" if mentioned(body, r"framer") else
            "WordPress" if mentioned(body, r"wordpress") else ""
        )
        intro = ("ваш заказ на лендинг" if mentioned(body, r"лендинг|landing") else
                 "ваш проект по разработке сайта")
        if platform:
            intro += f" на {platform}"
        detail = ("Могу продумать структуру страниц, подготовить аккуратный адаптивный дизайн "
                  "и довести сайт до удобного использования на мобильных устройствах.")
        evidence = "Занимаюсь веб-дизайном и digital-проектами, в портфолио есть работы для Avito."
        next_step = "Готов изучить исходные макеты или текущий сайт и обсудить сроки, объём и бюджет."

    elif cat == "uiux" or mentioned(body, r"ui.?ux|интерфейс|\bfigma\b|дизайн.?систем|прототип"):
        intro = "ваш проект по UI/UX-дизайну"
        specifics = []
        if mentioned(body, r"мобильн|\bios\b|\bandroid\b"):
            specifics.append("мобильные сценарии")
        if mentioned(body, r"дизайн.?систем|ui.?kit|компонент"):
            specifics.append("систему компонентов")
        if mentioned(body, r"ux.?аудит|аудит|юзабилити"):
            specifics.append("UX-аудит текущих экранов")
        detail = ("Могу помочь проработать пользовательские сценарии, "
                  "структуру экранов и адаптивные макеты в Figma.")
        if specifics:
            detail = "В запросе выделил ключевые задачи: " + ", ".join(specifics[:3]) + ". " + detail
        evidence = "Работаю с веб-дизайном и интерфейсами, есть опыт digital-проектов для Avito."
        next_step = "Готов посмотреть прототипы или текущие экраны и обсудить объём и этапы работы."

    elif cat == "presentations" or mentioned(body, r"презентац|слайд|pitch.?deck|powerpoint"):
        intro = "ваш запрос на дизайн презентации"
        deck = re.search(r"\b(\d{1,3})\s*(?:слайд(?:ов|а)?|стр(?:аниц|аницы)?)", body, re.I)
        detail = ("Могу выстроить единую структуру, типографику и визуальный стиль, "
                  "сделать диаграммы и инфографику понятными и удобными для восприятия.")
        if deck:
            detail = f"Увидел объём около {deck.group(1)} слайдов. " + detail
        evidence = ("Специализируюсь на презентациях и инфографике, в портфолио есть проекты "
                    "для Avito и Haval.")
        next_step = "Готов оценить исходные материалы, сроки и стоимость после просмотра брифа."

    elif mentioned(body, r"smm|соцсет|пост|карусел|рекламн|баннер"):
        intro = "ваш запрос на оформление digital-материалов"
        detail = ("Могу собрать единый визуальный подход для постов, рекламных макетов "
                  "и инфографики с упором на читаемость и узнаваемость.")
        evidence = "В портфолио есть рекламная графика и визуальные системы для Avito и Haval."
        next_step = "Готов посмотреть текущие материалы, объём и сроки задач."

    else:
        intro = "ваш проект по графическому дизайну"
        detail = ("Могу помочь с визуальной концепцией, типографикой "
                  "и аккуратной подготовкой макетов под нужные форматы.")
        evidence = "В моём портфолио есть проекты для Avito и Haval."
        next_step = "Готов ознакомиться с подробным ТЗ, обсудить сроки и бюджет."

    # The user represents themself as a designer, not an agency or director.
    return (
        "Здравствуйте!\n\n"
        f"Меня зовут Вячеслав, я независимый дизайнер. Заинтересовал {intro}.\n\n"
        f"{detail}\n\n"
        f"{evidence}\n\n"
        f"Портфолио: {PORTFOLIO}\n\n"
        f"Подскажите, задача ещё актуальна? {next_step}"
    )
