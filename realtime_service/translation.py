"""On-demand translation of publicly posted design briefs.

Uses a public machine-translation endpoint only after the user explicitly
requests a translation. The source text is never modified or sent to the
customer. Successful translations are cached by original-text digest.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

import requests

MAX_TEXT=12000
GOOGLE_URL="https://translate.googleapis.com/translate_a/single"
CHROME_URL="https://clients5.google.com/translate_a/t"
MYMEMORY_URL="https://api.mymemory.translated.net/get"


def looks_english(text: str) -> bool:
    sample=(text or "")[:5000]
    letters=re.findall(r"[A-Za-zА-Яа-яЁё]",sample)
    if len(letters)<35:return False
    latin=sum(c.isascii() for c in letters)
    return latin/len(letters)>.72


def body_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunks(text: str, size: int=850) -> list[str]:
    """Split on paragraph/sentence/word boundaries, not arbitrary bytes."""
    if not text:return []
    if size<80:raise ValueError("Invalid chunk size")
    parts=[]
    remaining=text.strip()
    while remaining:
        if len(remaining)<=size:
            parts.append(remaining)
            break
        search=remaining[:size+1]
        cut=max(search.rfind("\n\n"),search.rfind("\n"),
                search.rfind(". "),search.rfind("; "),search.rfind(" "))
        if cut<size//3:cut=size
        else:cut+=1 if search[cut]==" " else 0
        parts.append(remaining[:cut].strip())
        remaining=remaining[cut:].strip()
    return [p for p in parts if p]


def _chrome_translate(chunk: str) -> str:
    response=requests.get(CHROME_URL,params={
        "client":"dict-chrome-ex","sl":"en","tl":"ru","q":chunk
    },timeout=(4,12),headers={"User-Agent":"Mozilla/5.0"})
    response.raise_for_status()
    payload=response.json()
    if not isinstance(payload,list):raise ValueError("Unexpected translation result")
    return " ".join(p for p in payload if isinstance(p,str)).strip()


def _google(chunk: str) -> str:
    response=requests.get(GOOGLE_URL,params={
        "client":"gtx","sl":"en","tl":"ru","dt":"t","q":chunk
    },timeout=(4,12),headers={"User-Agent":"Mozilla/5.0"})
    response.raise_for_status()
    payload=response.json()
    return "".join(segment[0] for segment in payload[0]
                   if isinstance(segment,list) and segment and isinstance(segment[0],str)).strip()


def _mymemory(chunk: str) -> str:
    response=requests.get(MYMEMORY_URL,params={"q":chunk,"langpair":"en|ru"},
                          timeout=(4,12),headers={"User-Agent":"SearchOrders local translator"})
    response.raise_for_status()
    payload=response.json()
    if int(payload.get("responseStatus",200))!=200:raise ValueError("Translation unavailable")
    return str(payload.get("responseData",{}).get("translatedText","")).strip()


def translate_to_russian(text: str) -> str:
    if not text.strip() or len(text)>MAX_TEXT:raise ValueError("Description is too long or empty")
    if not looks_english(text):raise ValueError("English source text is required")
    translated=[]
    for part in chunks(text):
        try:
            result=_chrome_translate(part)
        except (requests.RequestException,ValueError,IndexError,TypeError,KeyError):
            try:
                result=_google(part)
            except (requests.RequestException,ValueError,IndexError,TypeError,KeyError):
                result=_mymemory(part)
        if len(result)<3 or not re.search(r"[А-Яа-яЁё]",result):
            raise ValueError("Translation provider returned incomplete or untranslated text")
        translated.append(result)
    return "\n\n".join(translated)
