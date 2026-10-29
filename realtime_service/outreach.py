"""Short, grounded outreach: first analyse the exact job, then write a fresh reply.

Optional OpenAI Responses API powers genuinely new natural-language drafts. When no
API key is configured, a transparent local context-aware variant generator is used.
Neither mode sends messages or makes up credentials, prices or client case studies.
"""
from __future__ import annotations

import difflib
import json
import random
import re
from typing import Any, Mapping, Sequence

import requests

PORTFOLIO = "https://samsel.site"
RNG = random.SystemRandom()
MODEL_DEFAULT = "gpt-4.1-mini"

def contains(s: str, pattern: str) -> bool:
    return bool(re.search(pattern, s, re.I))

def pick(seq):
    return RNG.choice(tuple(seq))

def analyse_brief(lead: Mapping[str, Any]) -> dict:
    text = re.sub(r"\s+", " ", str(lead.get("body") or "")).strip()[:3600]
    cat = str(lead.get("category") or "")
    tags = []
    type_name = ""
    detail = []
    constraint = []
    question = ""
    if contains(text,r"wildberries|\bwb\b|ozon|маркетплейс|карточ(?:ек|ки|ку) товар"):
        kind = "marketplace"
        type_name = "карточкам товаров для маркетплейсов"
        mapping = [
            (r"wildberries|\bwb\b","Wildberries"),
            (r"\bozon\b","Ozon"),
            (r"инфографик","инфографика"),
            (r"обложк|перв.{0,10}слайд","обложки карточек"),
            (r"ретуш|обработк.{0,12}фото","обработка фото"),
            (r"единый стиль|фирменн.{0,15}стил","единый стиль карточек"),
        ]
        question="Сколько товаров в первой партии и есть ли исходные фото?"
    elif contains(text,r"этикетк|флакон|коробк|упаковк|косметик|beauty.brand"):
        kind="packaging"
        type_name="дизайну упаковки"
        mapping=[
            (r"логотип","логотип"),
            (r"фирменн.{0,12}стил|айдентик","фирменный стиль"),
            (r"этикетк","этикетка"),
            (r"флакон","флакон"),
            (r"коробк","коробка"),
            (r"печатн|полиграф|типограф|печати|cmyk|вылет|тиснени","печатные материалы"),
            (r"косметик|бьюти|beauty","бьюти-продукт"),
        ]
        question="Есть ли размеры упаковки и требования типографии?"
    elif contains(text,r"лендинг|tilda|тильд|webflow|framer|редизайн сайта|сайт.{0,60}(блок|страниц)"):
        kind="web"
        type_name="лендингу" if contains(text,r"лендинг|landing") else "сайту"
        mapping=[
            (r"tilda|тильд","Tilda"),
            (r"webflow","Webflow"),
            (r"framer","Framer"),
            (r"\bfigma\b","макеты в Figma"),
            (r"адаптив|мобильн","мобильная версия"),
            (r"редизайн","редизайн текущей страницы"),
            (r"с нуля","разработка с нуля"),
            (r"\b(\d+)\s*[–-]\s*(\d+)\s*блок","блоки"),
            (r"маркетингов.{0,18}агентств","маркетинговое агентство"),
            (r"интернет-магазин","интернет-магазин"),
        ]
        count=re.search(r"\b(\d{1,2})\s*[–-]\s*(\d{1,2})\s*блок",text,re.I)
        if count: detail.append(f"{count.group(1)}–{count.group(2)} блоков")
        question="Есть ли референсы и к какому сроку нужен сайт?"
    elif contains(text,r"презентац|питч.?дек|pitch.?deck|\bслайд|powerpoint") or cat=="presentations":
        kind="presentations"
        type_name="презентации"
        mapping=[
            (r"един(?:ый|ому) стил|привести.{0,40}стил","единый визуальный стиль"),
            (r"инфографик|диаграмм|график","инфографика и графики"),
            (r"pitch.?deck|питч.?дек","коммерческий питч"),
            (r"редактируем|powerpoint|\bppt","редактируемый файл"),
            (r"срочн|сегодня|завтра","срочный срок"),
        ]
        count=re.search(r"\b(\d{1,3})\s*слайд",text,re.I)
        if count:detail.append(f"{count.group(1)} слайдов")
        question="Можете показать пару исходных слайдов и уточнить дедлайн?"
    elif contains(text,r"ux.?ui|ui.?ux|интерфейс|\bios\b|android|дизайн.?систем|прототип") or cat=="uiux":
        kind="uiux"
        type_name="дизайну интерфейсов"
        mapping=[
            (r"\bios\b|iphone","iOS"),
            (r"android","Android"),
            (r"дизайн.?систем|design.system","дизайн-система"),
            (r"прототип","прототипы"),
            (r"widget|виджет","виджеты"),
            (r"ux.?аудит|аудит","UX-аудит"),
            (r"мобильн","мобильный продукт"),
            (r"фигм|figma","Figma"),
        ]
        question="Есть ли текущие экраны или прототип, чтобы оценить объём?"
    elif contains(text,r"логотип|брендбук|айдентик|фирменн.{0,16}стил|ребрендинг"):
        kind="branding"
        type_name="фирменному стилю"
        mapping=[
            (r"логотип","логотип"),
            (r"брендбук","брендбук"),
            (r"айдентик|фирменн.{0,15}стил","айдентика"),
            (r"типографик","типографика"),
            (r"ребрендинг","обновление бренда"),
            (r"строительн","строительная компания"),
            (r"мероприят|ивент|event","материалы мероприятий"),
        ]
        question="Есть ли текущий стиль, референсы и список нужных носителей?"
    else:
        kind="graphics"
        type_name="графическому дизайну"
        mapping=[
            (r"полиграф|печатн.{0,12}материал","печатные материалы"),
            (r"рекламн|баннер","рекламные баннеры"),
            (r"соцсет|пост|сторис","визуалы для соцсетей"),
            (r"графическ.{0,15}дизайн","графический дизайн"),
            (r"обложк","обложки"),
            (r"каталог","каталог"),
        ]
        question="Какой объём задач планируется и в какие сроки?"
    for regex,fact in mapping:
        if contains(text,regex) and fact not in detail:detail.append(fact)
    # Prefer specific deliverables, not broad employer categories or generic tools.
    specifics=[f for f in detail if f not in ["бьюти-продукт","маркетинговое агентство","графический дизайн","Figma"]]
    if "6–9 блоков" in specifics or any(" блоков" in x for x in specifics):
        specifics=[x for x in specifics if x!="блоки"]
    if not specifics:specifics=detail
    if contains(text,r"срочн|сегодня|завтра"):constraint.append("срочные сроки")
    if contains(text,r"английск"):constraint.append("базовый английский")
    if contains(text,r"предоплат"):constraint.append("условия оплаты")
    if contains(text,r"небольш.{0,15}занятост|оперативн"):constraint.append("оперативность при небольшой загрузке")
    return {"kind":kind,"topic":type_name,"facts":specifics[:6],"constraints":constraint,
            "question":question,"source":text}

OPENERS=[
 "Здравствуйте! Увидел ваш запрос по {topic}.",
 "Добрый день! Заинтересовала ваша задача по {topic}.",
 "Здравствуйте! Пишу по вашему запросу на дизайн.",
 "Добрый день! Хотел бы откликнуться на ваш проект по {topic}.",
 "Здравствуйте! Увидел задачу по {topic} и решил написать.",
 "Добрый день! Заинтересовал ваш проект по {topic}.",
]
IDENTITY=[
 "Я Вячеслав, занимаюсь дизайном и работаю самостоятельно.",
 "Меня зовут Вячеслав, я дизайнер, работаю на проектной основе.",
 "Я Вячеслав, работаю дизайнером на проектах.",
 "Меня зовут Вячеслав. Работаю как самостоятельный дизайнер.",
]
FINISH=[
 "Буду рад обсудить проект. {question}",
 "Подскажите, задача ещё актуальна? {question}",
 "Если ещё ищете дизайнера, напишите, пожалуйста. {question}",
 "Могу оценить работу после уточнения деталей. {question}",
 "Буду рад подключиться, если проект открыт. {question}",
]

PRACTICE={
"web":[
 "Могу собрать структуру страницы, продумать подачу и адаптив.",
 "Возьму на себя дизайн страницы и проверю, чтобы она хорошо работала на мобильных устройствах.",
 "Сделаю аккуратную структуру и адаптивную версию без лишних визуальных элементов.",
 "Могу проработать блоки, визуальную иерархию и мобильную версию.",
],
"packaging":[
 "Могу продумать визуальный стиль и подготовить макеты с учётом требований печати.",
 "Интересно поработать над цельным решением от айдентики до печатных носителей.",
 "Могу предложить визуальную концепцию и подготовить файлы для производства.",
],
"presentations":[
 "Могу привести материал к единой сетке, типографике и понятной визуальной логике.",
 "Помогу оформить слайды в едином стиле, сохранив структуру и читабельность.",
 "Могу аккуратно собрать презентацию, выделить ключевые цифры и упорядочить сложные блоки.",
],
"uiux":[
 "Могу проработать логику экранов, компоненты и понятную визуальную систему.",
 "Помогу со структурой интерфейса и рабочими макетами в Figma.",
 "Могу посмотреть текущие сценарии и предложить аккуратное решение по интерфейсу.",
],
"branding":[
 "Могу проработать визуальную концепцию и систему применения фирменного стиля.",
 "Возьмусь за айдентику и оформление носителей в едином визуальном языке.",
 "Могу предложить цельный визуальный подход и подготовить нужные макеты.",
],
"marketplace":[
 "Могу собрать наглядные карточки с понятной иерархией преимуществ товара.",
 "Помогу сделать обложки и инфографику едиными по стилю и читаемыми на телефоне.",
 "Могу выстроить визуал карточек вокруг ключевых характеристик товара.",
],
"graphics":[
 "Могу помочь с визуальной концепцией и подготовкой макетов под нужные форматы.",
 "Могу подхватить задачи по графике и быстро согласовывать материалы.",
 "Помогу выстроить единый визуальный подход и аккуратно подготовить файлы.",
]
}
FACT_FRAMING=[
 "Обратил внимание на конкретные задачи: {facts}.",
 "Вижу, что в работе важны {facts}.",
 "По описанию, основной объём здесь: {facts}.",
 "Особенно интересна часть с {facts}.",
 "Понял задачу как работу над {facts}.",
]

def natural_details(analysis: dict) -> str:
    """Brief-specific fact sentence: use grammatical constructions, not raw keyword lists."""
    text=analysis["source"]
    kind=analysis["kind"]
    found=analysis["facts"]
    if kind=="web":
        platform=next((x for x in ("Tilda","Webflow","Framer") if x in found),"")
        blocks=next((x for x in found if " блоков" in x),"")
        subject=("лендинг" if "лендинг" in analysis["topic"] else "сайт")
        suffix=(" на "+platform if platform else "")
        pieces=[]
        if blocks:pieces.append(blocks)
        if "разработка с нуля" in found:pieces.append("разработка с нуля")
        if "мобильная версия" in found:pieces.append("адаптив")
        context=" для маркетингового агентства" if "маркетинговое агентство" in found else ""
        overview=(f"{subject}{suffix}{context}"+(f", {', '.join(pieces)}" if pieces else ""))
        return pick([
           f"По описанию, нужен {overview}.",
           f"Вижу задачу: {overview}.",
           f"Увидел, что требуется {overview}.",
        ])
    if kind=="packaging":
        specific=[]
        for item in ["логотип","фирменный стиль","этикетка","флакон","коробка","печатные материалы"]:
            if item in found:specific.append(item)
        if "базовый английский" in analysis["constraints"]:specific.append("базовый английский")
        if "оперативность при небольшой загрузке" in analysis["constraints"]:specific.append("оперативность")
        if not specific:specific=["упаковка и макеты для печати"]
        return pick([
            "По описанию, важны "+", ".join(specific[:4])+".",
            "Увидел ваши требования: "+", ".join(specific[:4])+".",
            "Понял задачу: "+", ".join(specific[:4])+".",
        ])
    if kind=="presentations":
        count=next((x for x in found if " слайдов" in x),"")
        if count:
            return pick([f"Увидел объём {count}, важно привести материал к единому стилю.",
                         f"Понял задачу: {count} нужно оформить в одной визуальной системе.",
                         f"Вижу, что требуется оформление {count}; особенно важно согласовать объём и сроки."])
    if kind=="uiux":
        specifics=[f for f in found if f in ("iOS","Android","виджеты","дизайн-система","прототипы","UX-аудит")]
        if specifics:return "По описанию, в приоритете "+", ".join(specifics[:3])+"."
    if kind=="marketplace":
        specifics=[x for x in found if x in ("Wildberries","Ozon","инфографика","обложки карточек","обработка фото")]
        if specifics:return pick(["Увидел задачи по карточкам: "+", ".join(specifics[:3])+".",
                                  "Вижу, что нужны "+", ".join(specifics[:3])+"."])
    if kind in ("branding","graphics"):
        if found:return pick(["По задаче вижу фокус на "+", ".join(found[:2])+".",
                              "В объявлении выделил "+", ".join(found[:2])+"."])
    return ""

def local_draft(facts: dict, previous: Sequence[str] = ()) -> str:
    """Human-readable local fallback; never present it as model generation."""
    kind=facts["kind"]
    topic=facts["topic"]
    question=facts["question"]
    grounded=natural_details(facts)
    best_text=None
    best_score=-1
    for _ in range(110):
        opener=pick(OPENERS).format(topic=topic)
        identity=pick(IDENTITY)
        professional=pick(PRACTICE[kind])
        ending=pick(FINISH).format(question=question)
        core=" ".join(x for x in (grounded,professional) if x)
        draft=f"{opener} {identity}\n\n{core}\n\nПортфолио: {PORTFOLIO}\n\n{ending}\n\nС уважением,\nВячеслав"
        sim=max((difflib.SequenceMatcher(None,draft,p).ratio() for p in previous[:25]),default=0)
        if draft not in previous and sim<0.82:return draft
        if 1-sim>best_score:best_score=1-sim;best_text=draft
    return best_text or draft

INSTRUCTIONS="""Ты пишешь КОРОТКИЕ индивидуальные письма по электронной почте для проектных заказчиков от имени Вячеслава,
самостоятельного дизайнера (не директора и не агентства). Прочитай объявление целиком;
выбери 1–3 наиболее конкретных требования и ответь именно на них.
Напиши текст на ЯЗЫКЕ ОБЪЯВЛЕНИЯ: на английском, если исходник английский; на русском, если исходник русский. 45–90 слов, без длинной самопрезентации, без канцелярита,
пустых комплиментов, искусственных рекламных фраз и клише. Голос естественный и дружелюбно-деловой.
Ссылку https://samsel.site укажи один раз.
Не вставляй Avito, Haval и другие бренды, если они не нужны самому заказчику.
Не приписывай исполнителю дипломы, опыт печати, кейсы, специализации или сроки,
которые не подтверждены: допустимо лишь предложить помощь с заявленными задачами.
Не обещай выполнить невыполнимое. Бюджет не выдумывай.
Если в объявлении есть конкретные размеры, объём, платформа, печать, дедлайн,
покажи, что ты заметил именно эти детали.
Заверши одним уместным вопросом, если он нужен.
Пиши новый вариант, не повторяя фразы и структуру прошлых писем.
НЕ добавляй вступление от нейросети, кавычки, подпись должности или пояснения.
"""

def ai_draft(lead:Mapping[str,Any], analysis:dict, previous:Sequence[str], api_key:str, model:str=MODEL_DEFAULT) -> str:
    prompt=json.dumps({
      "объявление":analysis["source"],"задача":analysis["topic"],
      "детали_объявления":analysis["facts"],"ограничения":analysis["constraints"],
      "предыдущие_версии_этого_отклика_НЕ_повторять":list(previous[:6]),
      "инструкция":"Создай новую короткую версию email-отклика по конкретному объявлению. Приветствие, суть, портфолио и подпись «С уважением, Вячеслав» обязательны. Тему письма приложение создаст отдельно."
    },ensure_ascii=False)
    response=requests.post("https://api.openai.com/v1/responses",
      headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"},
      json={"model":model,"instructions":INSTRUCTIONS,"input":prompt,"store":False,"max_output_tokens":400},
      timeout=(6,38))
    response.raise_for_status()
    data=response.json()
    texts=[a.get("text","") for m in data.get("output",[]) if m.get("type")=="message"
           for a in m.get("content",[]) if a.get("type")=="output_text"]
    draft="\n".join(texts).strip().strip('«»"')
    return draft

def valid_draft(text:str,analysis:dict,previous:Sequence[str])->bool:
    if not 120<=len(text)<=950:return False
    if not PORTFOLIO in text or text.count(PORTFOLIO)!=1:return False
    if contains(text,r"креативн.{0,8}директор|creative lead|арт.?директор|руководитель|\bAvito\b|\bHaval\b"):return False
    if contains(text,r"гарантирую|бесплатн.{0,12}тест|скидка\s*\d+|опыт.{0,12}\d+\s*лет"):return False
    # Normalize to compare meaningfully across repeated generations.
    compare=lambda x:re.sub(r"\s+"," ",x.lower()).strip()
    for past in previous:
      if compare(text)==compare(past) or difflib.SequenceMatcher(None,compare(text),compare(past)).ratio()>0.84:
       return False
    if analysis["facts"]:
      source_hits=sum(contains(text,re.escape(f)) for f in analysis["facts"][:5])
      # AI can paraphrase details; requiring literal tokens is too strict.
      if not source_hits and not any(t.lower() in text.lower() for t in analysis["source"].split() if len(t)>9):
       return False
    return True

def english_brief(source: str)->bool:
    """Decide by content language, not sender email domain."""
    letters=re.findall(r"[A-Za-zА-Яа-яЁё]",source)
    if not letters:return False
    latin=sum(1 for c in letters if "A"<=c<="Z" or "a"<=c<="z")
    return latin/len(letters)>0.75

def english_local_draft(brief: Mapping[str,Any], previous: Sequence[str]=())->str:
    """No fabricated qualifications, prices, or customer-specific successes."""
    source=brief["source"].lower()
    if "transparency international" in source or "tender for freelance" in source:
        context="your call for freelance designers supporting publications, visual materials and data visualizations"
        capability="editorial layouts, clear visual communication and information-heavy design"
        question="Could you confirm the format for submitting rates and supporting documents?"
    elif "future london academy" in source or "occasional project" in source:
        context="your invitation to freelance designers for upcoming project-based collaborations"
        capability="presentation design, visual communication and brand-consistent creative work"
        question="Would it be useful to discuss the kinds of projects you expect to commission?"
    elif "makkai hang" in source or "typography" in source:
        context="your freelance Graphic Designer opportunity"
        capability="typography, layout and consistent visual identities"
        question="Are you currently reviewing freelance applicants for the upcoming project?"
    else:
        context="your freelance design brief"
        if re.search(r"pitch deck|presentation|slides",source,re.I):
            context="your presentation design project"
            capability="clear slide structures, typography and visual storytelling"
        elif re.search(r"website|landing page|web design",source,re.I):
            context="your website design project"
            capability="page structure, responsive design and visual hierarchy"
        elif re.search(r"ui/ux|interface|product design",source,re.I):
            context="your product design brief"
            capability="interface layout, usability and cohesive components"
        else:
            capability="visual concepts and production-ready design materials"
        question="Could you share the scope and expected timeline?"
    intro=(
        f"Hello,\n\nI saw {context} and would like to apply.",
        f"Hi,\n\nI'm interested in {context}.",
        f"Hello,\n\nI came across {context} and wanted to get in touch.",
        f"Hi,\n\nI would be glad to be considered for {context}.",
    )
    middle=(
        f"I'm Vyacheslav, an independent designer. My work includes {capability}.",
        f"My name is Vyacheslav, and I work independently as a designer, with a focus on {capability}.",
        f"I'm an independent designer working across {capability}.",
        f"I work as an independent designer and can help with {capability}.",
    )
    ending=(
        question,
        "Is the opportunity still open to external freelancers?",
        "I'd be happy to share more detail about relevant work if useful.",
        "Please let me know the next steps for a freelance application.",
    )
    best=None
    best_similarity=10.0
    for _ in range(120):
        text=(pick(intro)+"\n\n"+pick(middle)+
              f"\n\nPortfolio: {PORTFOLIO}\n\n"+pick(ending)+
              "\n\nBest regards,\nVyacheslav")
        score=max((difflib.SequenceMatcher(None,text,p).ratio() for p in previous[:25]),default=0)
        if score<.82 and text not in previous:return text
        if score<best_similarity:best_similarity=score;best=text
    return best or text

def subject_for_brief(analysis: Mapping[str,Any]) -> str:
    """Grounded short email subject, no unrelated brand references."""
    source=str(analysis.get("source") or "")
    if english_brief(source):
        patterns=[
            r"with the subject line\s*[\'\"“]([^\'\"”]{4,85})[\'\"”]",
            r"indicate\s*[\'\"“]([^\'\"”]{4,85})[\'\"”]\s+in the subject line",
            r"subject:\s*([A-Za-z][A-Za-z \-/]{5,80})"
        ]
        for pattern in patterns:
            m=re.search(pattern,source,re.I)
            if m:return m.group(1).strip()
        if re.search(r"please indicate.{0,25}freelance graphic designer.{0,25}in the subject",source,re.I):return "Freelance Graphic Designer"
        if re.search(r"graphic designer",source,re.I):return "Freelance Graphic Designer | Vyacheslav Samsel"
        if re.search(r"presentation|pitch deck|slides",source,re.I):return "Freelance Presentation Designer | Vyacheslav Samsel"
        if re.search(r"ui/ux|interface|product designer",source,re.I):return "Freelance UI/UX Designer | Vyacheslav Samsel"
        if re.search(r"web design|website|landing page",source,re.I):return "Freelance Web Designer | Vyacheslav Samsel"
        return "Freelance Graphic Designer | Vyacheslav Samsel"
    kind=str(analysis.get("kind") or "")
    facts=analysis.get("facts") or []
    if kind=="web":
        platform=next((f for f in ("Tilda","Webflow","Framer") if f in facts),"")
        return "Отклик на проект: "+("лендинг" if "лендинг" in analysis.get("topic","") else "дизайн сайта")+(" на "+platform if platform else "")
    if kind=="presentations":
        volume=next((f for f in facts if " слайдов" in f),"")
        return "Отклик: дизайн презентации"+(" · "+volume if volume else "")
    if kind=="packaging":return "Отклик: дизайн упаковки и айдентика"
    if kind=="marketplace":return "Отклик: дизайн карточек товаров"
    if kind=="uiux":return "Отклик: UI/UX-дизайн"
    if kind=="branding":return "Отклик: фирменный стиль и графика"
    return "Отклик: графический дизайн"

def create_draft(lead:Mapping[str,Any],previous:Sequence[str]=(),api_key:str="",model:str=MODEL_DEFAULT)->tuple[str,str,dict]:
    brief=analyse_brief(lead)
    if api_key:
      for _ in range(2):
        try:
          draft=ai_draft(lead,brief,previous,api_key,model)
          if valid_draft(draft,brief,previous):return draft,"ai",brief
        except (requests.RequestException, ValueError,KeyError):
          break
    local=(english_local_draft(brief,previous) if english_brief(brief["source"])
           else local_draft(brief,previous))
    return local,"local",brief
