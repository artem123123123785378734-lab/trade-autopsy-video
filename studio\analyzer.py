"""Script analysis: sentences -> scenes -> visual plan.

No external AI is required. The planner uses linguistic heuristics tuned for
Russian trading content: it finds numbers, pain points, CTAs and picks a visual
treatment that fits each scene. The same input always produces the same plan.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field, asdict

from . import gfx

# ---------------------------------------------------------------- text utils
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF"
    "\U0001F1E6-\U0001F1FF\uFE0F\u200D]+"
)
SPACE_RE = re.compile(r"[ \t\u00a0]+")
ABBREV = ("т.е.", "т.д.", "т.п.", "др.", "г.", "гг.", "руб.", "млн.", "млрд.")


def clean_for_speech(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = URL_RE.sub("ссылка", text)
    text = EMOJI_RE.sub(" ", text)
    text = re.sub(r"[*_#`>]+", " ", text)
    text = re.sub(r"[«»“”„]", '"', text)
    text = SPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _protect_abbrev(text: str) -> str:
    out = text
    for i, ab in enumerate(ABBREV):
        out = out.replace(ab, f"\u0001{i}\u0001")
    return out


def _restore_abbrev(text: str) -> str:
    for i, ab in enumerate(ABBREV):
        text = text.replace(f"\u0001{i}\u0001", ab)
    return text


def split_sentences(text: str) -> list[str]:
    """Split into paragraphs and sentences, keeping question/exclamation marks."""
    text = clean_for_speech(text)
    if not text:
        return []
    result: list[str] = []
    for paragraph in re.split(r"\n+", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        protected = _protect_abbrev(paragraph)
        pieces = re.split(r"(?<=[.!?…])\s+", protected)
        for piece in pieces:
            piece = _restore_abbrev(piece).strip()
            if not piece:
                continue
            # Very long sentences are hard to read on screen: split at a comma
            # close to the middle, but never into tiny fragments.
            while len(piece) > 210:
                cut = _best_comma_cut(piece)
                if cut <= 0:
                    break
                result.append(piece[:cut].strip())
                piece = piece[cut:].strip(" ,;:—–-")
            if piece:
                result.append(piece)
    return result


def _best_comma_cut(text: str) -> int:
    mid = len(text) // 2
    positions = [m.start() + 1 for m in re.finditer(r"[,;:]\s", text)]
    positions = [p for p in positions if 60 <= p <= len(text) - 40]
    if not positions:
        positions = [m.start() + 1 for m in re.finditer(r"\s", text)
                     if 80 <= m.start() <= len(text) - 40]
    if not positions:
        return 0
    return min(positions, key=lambda p: abs(p - mid))


SPEECH_REPLACEMENTS = [
    (r"\bP\s*&\s*L\b", "пи энд эл"),
    (r"\bПроп-режим\b", "проп режим"),
    (r"\bR-мультипликатор\b", "эр-мультипликатор"),
    (r"\bequity\b", "эквити"),
    (r"\bwinrate\b", "винрейт"),
    (r"\bSMC\b", "эс-эм-си"),
    (r"\bTrade\s+Autopsy\b", "Трейд Автопси"),
    (r"\bPremium\b", "Премиум"),
    (r"\bBoosty\b", "Бусти"),
    (r"\bTelegram\b", "Телеграм"),
    (r"\bTikTok\b", "ТикТок"),
]


def speech_text(text: str) -> str:
    """Russian TTS pronounces English trading terms badly; spell them out."""
    out = text
    for pattern, repl in SPEECH_REPLACEMENTS:
        out = re.sub(pattern, repl, out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()


def estimate_seconds(text: str, rate: int = 0) -> float:
    """Rough Russian speech duration at a given Edge TTS rate."""
    chars = len(re.sub(r"\s+", " ", text).strip())
    if not chars:
        return 0.0
    base = chars / 15.2
    base += 0.28 * len(re.findall(r"[.!?…]", text))
    return base * 100.0 / max(50.0, 100.0 + rate)


def suggest_rate(text: str, target: float | None) -> int:
    if not target:
        return 0
    seconds = estimate_seconds(text, 0)
    if seconds <= 0:
        return 0
    desired = max(8.0, target - 1.6)
    ratio = seconds / desired
    return int(max(-8, min(24, round((ratio - 1) * 100))))


# ---------------------------------------------------------------- metrics
NUM_RE = re.compile(
    r"(?<![\w])(\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(₽|руб(?:лей|ля|ль)?|процент(?:ов|а)?|%|\$|доллар(?:ов|а)?|"
    r"евро|€|дней|дня|день|недел(?:ь|и|ю)|сделок|сделки|сделку|R)(?![\w])",
    re.I,
)


def extract_metric(text: str) -> dict | None:
    matches = list(NUM_RE.finditer(text))
    if not matches:
        return None
    # Prefer money / percent; otherwise the first number.
    def score(m):
        unit = m.group(2).lower()
        if unit in ("₽", "$", "€") or unit.startswith("руб") or unit.startswith("процент") \
                or unit in ("%", "доллар", "евро"):
            return 3
        return 1

    m = max(matches, key=score)
    raw = m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    unit_raw = m.group(2)
    unit = unit_raw.lower()
    prefix = ""
    suffix = unit_raw
    if unit in ("₽",) or unit.startswith("руб"):
        suffix = "₽"
    elif unit in ("$",) or unit.startswith("доллар"):
        suffix = "$"
    elif unit in ("€", "евро"):
        suffix = "€"
    elif unit.startswith("процент") or unit == "%":
        suffix = "%"
    elif unit.startswith("дн"):
        suffix = "дн."
    elif unit.startswith("недел"):
        suffix = "нед."
    elif unit.startswith("сдел"):
        suffix = "сделок"
    elif unit == "r":
        suffix = "R"
    # "минус 17 процентов" -> show a minus
    before = text[max(0, m.start() - 14):m.start()].lower()
    if re.search(r"(минус|−|-)\s*$", before):
        prefix = "−"
    # Context label (2-4 words after the number).
    after = re.split(r"[.!?…]", text[m.end():m.end() + 60], maxsplit=1)[0]
    after = after.strip(" .,;:—-")
    label_words = after.split()[:3]
    label = " ".join(label_words).strip(" .,;:—-")
    if label.lower() in ("в месяц", "в год", "за месяц", "за год"):
        label = label.lower()
    return {
        "raw": m.group(0),
        "value": value,
        "prefix": prefix,
        "suffix": suffix,
        "label": label,
    }


# ---------------------------------------------------------------- phrases
STOP_START = {
    "а", "и", "но", "это", "ты", "вы", "мы", "я", "в", "во", "на", "с", "со",
    "по", "для", "что", "как", "если", "когда", "то", "же", "у", "о", "об",
    "из", "за", "от", "до", "не", "уже", "ещё", "еще", "просто", "вот", "там",
    "тут", "так", "потому", "поэтому", "который", "которая", "которые",
    "того", "он", "она", "они", "оно", "этот", "эта", "эти", "свой", "своих",
}
STOP_TAIL = {
    "и", "в", "во", "на", "с", "со", "по", "для", "из", "к", "ко", "у", "о",
    "об", "не", "а", "но", "что", "как", "или", "же", "ли", "то", "при",
    "от", "до", "за", "над", "под", "без", "через", "это",
}


def _words(text: str) -> list[str]:
    raw = re.findall(r"[A-Za-zА-Яа-яЁё0-9₽$%+&./\-]+", text)
    out = []
    for w in raw:
        w = w.strip(".,;:!?—–\"«»()")
        w = w.replace("–", "-")
        if w and w not in ("-", "—"):
            out.append(w)
    return out


def _trim_phrase(words: list[str], max_words: int = 6, max_chars: int = 38) -> str:
    while words and words[0].lower().strip(".,!?—–-") in STOP_START:
        words.pop(0)
    while words and words[-1].lower().strip(".,!?—–-") in STOP_TAIL:
        words.pop()
    if len(words) > max_words:
        words = words[:max_words]
    while words and words[-1].lower().strip(".,!?—–-") in STOP_TAIL:
        words.pop()
    text = " ".join(words).strip(" ,.;:!?—–-")
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip(" ,.;:!?—–-")
        while text.split() and text.split()[-1].lower() in STOP_TAIL:
            text = " ".join(text.split()[:-1])
    return text


def key_phrase(text: str, max_words: int = 5, max_chars: int = 38) -> str:
    clauses = [c.strip(" ,.;:!?—–-") for c in re.split(
        r"[,;:—–]|[.!?…](?=\s|$)|(?<=\w)\s+(?:и|а|но)\s+", text) if c.strip()]
    clauses = [c for c in clauses if len(c) >= 4]
    if not clauses:
        clauses = [text]

    # Prefer a clause that contains digits or a strong trading word.
    strong = ("p&l", "r-мультипликатор", "журнал", "сделк", "риск", "депозит",
              "профит", "убыт", "тильт", "сетап", "premium", "smc", "equity")

    def score(c):
        low = c.lower()
        return ((2.4 if re.search(r"\d", c) else 0)
                + (1.2 if any(w in low for w in strong) else 0)
                + min(len(c), 40) / 80)

    clause = max(clauses, key=score)
    words = _words(clause)
    return _trim_phrase(words, max_words, max_chars)


def secondary_phrase(text: str, primary: str, max_words: int = 6, max_chars: int = 42) -> str:
    # The brand is a strong accent by itself.
    if "trade autopsy" in text.lower() and "trade autopsy" not in (primary or "").lower():
        return "Trade Autopsy"
    cleaned = text
    if primary:
        cleaned = re.sub(re.escape(primary), "", cleaned, count=1, flags=re.I)
    clauses = [c.strip(" ,.;:!?—–-") for c in re.split(
        r"[,;:—–]|[.!?…](?=\s|$)", cleaned) if c.strip()]
    clauses = [c for c in clauses if len(c) >= 7]
    if not clauses:
        return ""
    first = _trim_phrase(_words(clauses[0]), max_words, max_chars)
    if not first or len(first) < 4:
        return ""
    if len(clauses) > 1 and len(first) <= 12:
        second = _trim_phrase(_words(clauses[1]), max_words, max_chars)
        if second and len(second) >= 4:
            joined = f"{first} · {second}"
            if len(joined) <= max_chars + 8:
                return joined
    return first


def make_bullets(text: str, limit: int = 3, max_chars: int = 34) -> list[str]:
    raw = re.split(r"[,;:.]|(?<=\w)\s+(?:и|а|но)\s+", text)
    out = []
    for part in raw:
        part = part.strip(" ,.;:!?—–-\n")
        if len(part) < 4:
            continue
        words = _words(part)
        phrase = _trim_phrase(words, 6, max_chars)
        if phrase and phrase.lower() not in [x.lower() for x in out]:
            out.append(phrase)
        if len(out) >= limit:
            break
    return out


def _sentiment(text: str) -> float:
    low = text.lower()
    pos = len(re.findall(r"раст|прибыл|профит|работ|результат|плюс|доход|сильн|лучш|решен|спокой|контрол|дисциплин|понят", low))
    neg = len(re.findall(r"минус|убыт|теря|слив|тильт|ошибк|проблем|просад|стоп|наруш|хаос|риск|боль|слаб", low))
    return (pos - neg) / max(1, pos + neg)


# ---------------------------------------------------------------- scene types
TYPE_KICKERS = {
    "hook": "РАЗБОР",
    "statement": "ГЛАВНОЕ",
    "checklist": "ЧТО НЕ ТАК",
    "stat": "ЦИФРЫ",
    "chart": "ГРАФИК",
    "dashboard": "ЖУРНАЛ СДЕЛОК",
    "terminal": "ТЕРМИНАЛ",
    "diagram": "КАК ЭТО РАБОТАЕТ",
    "compare": "ДО / ПОСЛЕ",
    "notification": "УВЕДОМЛЕНИЕ",
    "bars": "СТАТИСТИКА",
    "timeline": "ШАГИ",
    "quote": "ПРАВИЛО",
    "cta": "НАЧНИ СЕЙЧАС",
    "outro": "TRADE AUTOPSY",
}

KEYWORDS: dict[str, tuple[str, ...]] = {
    "checklist": ("ошибк", "теря", "слив", "тильт", "переторг", "наруш", "проблем",
                  "стоп", "убыт", "боль", "минус", "слаб", "почему"),
    "dashboard": ("журнал", "сделк", "запис", "истор", "дневник", "статистик",
                  "сетап", "сделку", "таблиц", "вносишь", "загружаешь", "брокер",
                  "p&l", "эмоци", "тег"),
    "chart": ("график", "рост", "прибыл", "профит", "депозит", "equity",
              "просадк", "процент", "r-мультипликатор", "winrate", "результат"),
    "terminal": ("терминал", "ордер", "тейк", "стоп", "фьючерс", "позици",
                 "лот", "bid", "ask", "лимит", "проп", "плеч", "марж"),
    "diagram": ("как это работает", "систем", "процесс", "связк", "внутри",
                "автоматич", "пайплайн", "цикл", "схем"),
    "compare": ("до и после", "было", "стало", "вместо", "разниц", "сравн",
                "без журнала", "с журналом"),
    "notification": ("напомин", "уведомл", "бот", "telegram", "сообщени",
                     "недельный", "детектор", "приходит", "пришлёт", "пришлет"),
    "bars": ("по сетап", "по дням", "по ошибк", "распредел", "топ ", "чаще",
             "статистик", "процент"),
    "timeline": ("шаг", "этап", "сначала", "потом", "план", "начни",
                 "процесс", "сначала", "дальше"),
    "quote": ("правило", "закон", "запомни", "главное"),
}


def detect_type(text: str, index: int, total: int, prev: list[str],
                has_metric: bool, has_bullets: bool) -> str:
    if index == 0:
        return "hook"
    low = text.lower()
    scores: dict[str, float] = {}
    for kind, words in KEYWORDS.items():
        s = 0.0
        for w in words:
            if w in low:
                s += 2.2 if " " in w else 1.4
        if s:
            scores[kind] = s
    if has_metric:
        scores["stat"] = scores.get("stat", 0) + 2.8
    if re.search(r"\d", text) and re.search(r"₽|руб|%|\$|дн|сдел", low):
        scores["stat"] = scores.get("stat", 0) + 1.2
    if has_bullets:
        scores["checklist"] = scores.get("checklist", 0) + 0.8
        scores["timeline"] = scores.get("timeline", 0) + 0.4
    if re.search(r"\bшаг\b|\bэтап\b", low):
        scores["timeline"] = scores.get("timeline", 0) + 4.5
    # Unknown topic: rotate calm, generic explainer scenes.
    if not scores:
        rotation = ["statement", "diagram", "checklist", "timeline", "statement"]
        kind = rotation[index % len(rotation)]
        if prev and kind == prev[-1]:
            kind = "statement"
        return kind
    # Avoid repeating the same visual twice in a row.
    for k in list(scores):
        if prev and k == prev[-1]:
            scores[k] -= 1.7
        if len(prev) >= 2 and k == prev[-2]:
            scores[k] -= 0.6
    kind = max(scores, key=scores.get)
    if kind in ("checklist", "compare", "timeline") and not has_bullets:
        kind = "statement"
    if kind == "bars" and not has_bullets:
        kind = "stat" if has_metric else "diagram"
    if kind == "stat" and not has_metric:
        kind = "chart" if "график" in low or "прибыл" in low else "statement"
    return kind


# ---------------------------------------------------------------- demo visuals
DASH_ROWS = [
    ("12.11", "EURUSD", "SMC · M15", "+2.4R", "+$480"),
    ("11.11", "XAUUSD", "OB · H1", "-1.0R", "-$200"),
    ("11.11", "GBPUSD", "FVG · M5", "+1.8R", "+$360"),
    ("10.11", "BTCUSDT", "BOS · H4", "+3.1R", "+$620"),
]

BAR_LABELS = ["Сетап A", "Сетап B", "Сетап C", "Ликвидность"]


def make_chart(text: str, seed: int) -> dict:
    rng = random.Random(seed)
    sentiment = _sentiment(text)
    n = 38
    price = 1.084
    trend = sentiment * 0.00055
    candles = []
    for i in range(n):
        phase = -0.7 if i < n * 0.32 else 1.0
        drift = trend * phase + rng.gauss(0, 0.00075)
        o = price
        c_ = max(0.2, o + drift)
        hi = max(o, c_) + abs(rng.gauss(0, 0.00045))
        lo = min(o, c_) - abs(rng.gauss(0, 0.00045))
        candles.append({"o": o, "c": c_, "h": hi, "l": lo})
        price = c_
    lo = min(c["l"] for c in candles)
    hi = max(c["h"] for c in candles)
    span = max(1e-6, hi - lo)
    entry = candles[int(n * 0.34)]["o"]
    stop = entry - span * 0.22
    target = entry + span * 0.55
    return {
        "symbol": "EURUSD",
        "timeframe": "M15",
        "price": price,
        "candles": candles,
        "lo": lo,
        "hi": hi,
        "entry": entry,
        "stop": stop,
        "target": target,
        "change": (candles[-1]["c"] / candles[0]["o"] - 1) * 100,
    }


def make_compare(text: str) -> dict:
    low = text.lower()
    left = "БЕЗ ЖУРНАЛА"
    right = "С ЖУРНАЛОМ"
    if "до" in low and "после" in low:
        left, right = "ДО", "ПОСЛЕ"
    elif "было" in low and "стало" in low:
        left, right = "БЫЛО", "СТАЛО"
    return {
        "left": left,
        "right": right,
        "left_items": ["Сделки в голове", "Ошибки повторяются", "Нет цифр"],
        "right_items": ["Вся история в одном месте", "Видно, что съедает депозит", "Решения по данным"],
    }


def make_diagram(text: str) -> dict:
    low = text.lower()
    if any(w in low for w in ("журнал", "сделк", "разбор")):
        nodes = ["СДЕЛКА", "ЖУРНАЛ", "РАЗБОР", "РЕШЕНИЕ"]
    elif any(w in low for w in ("риск", "проп", "лимит")):
        nodes = ["РИСК", "ЛИМИТ", "СДЕЛКА", "ОТЧЁТ"]
    else:
        nodes = ["ВХОД", "СИСТЕМА", "КОНТРОЛЬ", "РЕЗУЛЬТАТ"]
    return {"nodes": nodes, "center": "TRADE AUTOPSY" if "trade" in low else "СИСТЕМА"}


# ---------------------------------------------------------------- main plan
@dataclass
class Scene:
    index: int
    id: str
    kind: str
    text: str
    title: str
    accent: str
    kicker: str
    note: str = ""
    badge: str = ""
    tone: str = ""
    bullets: list[str] = field(default_factory=list)
    metric: dict | None = None
    chart: dict | None = None
    compare: dict | None = None
    diagram: dict | None = None
    rows: list = field(default_factory=list)
    est: float = 0.0
    start: float = 0.0
    end: float = 0.0


def _scene_title(sentence: str, kind: str, video_title: str, index: int) -> tuple[str, str]:
    if kind == "hook":
        title = (video_title or key_phrase(sentence, 5, 30)).upper()
        accent = key_phrase(sentence, 6, 40)
        # If the title duplicates the phrase, pick the next clause.
        if accent and accent.upper()[:18] in title.upper():
            accent = secondary_phrase(sentence, accent, 6, 40)
        return title, (accent or "СМОТРИ ДАЛЬШЕ").upper()
    if kind == "cta":
        low = sentence.lower()
        if "начни" in low or "бесплат" in low or "попроб" in low:
            title = "НАЧНИ ВЕСТИ ЖУРНАЛ"
        elif "ссылк" in low:
            title = "ССЫЛКА В ПРОФИЛЕ"
        else:
            title = key_phrase(sentence, 4, 26) or "НАЧНИ СЕЙЧАС"
        accent = key_phrase(sentence, 5, 36)
        if "ссылк" in low and "ссылк" not in title.lower():
            accent = "ССЫЛКА В ПРОФИЛЕ"
        return title.upper(), accent.upper()
    title = key_phrase(sentence, 5, 34)
    accent = secondary_phrase(sentence, title, 5, 36)
    return (title or f"ЧАСТЬ {index + 1}").upper(), accent.upper()


def _note_for(kind: str, text: str, metric: dict | None) -> str:
    low = text.lower()
    if kind == "cta":
        return "7 дней бесплатно · без карты"
    if "без карты" in low:
        return "без карты · без обязательств"
    if "ссылка в профиле" in low:
        return "ссылка в профиле"
    if "2–3" in low or "2-3" in low or "два-три" in low:
        return "2–3 разбора в неделю"
    if "7 дней" in low or "семь дней" in low:
        return "7 дней бесплатно"
    if "telegram" in low:
        return "Telegram · закрытый клуб"
    if metric and metric.get("label"):
        return f"{metric['raw'].strip()}"
    defaults = {
        "chart": "без сигналов · только твои данные",
        "dashboard": "P&L · сетап · риск · эмоции",
        "terminal": "контроль лимитов в реальном времени",
        "diagram": "от сделки до решения",
        "checklist": "это видно в журнале",
        "compare": "разница — в цифрах",
        "notification": "отчёт приходит сам",
        "bars": "пример разбора",
        "timeline": "повторяй каждую неделю",
        "stat": "факт",
        "statement": "",
        "cta": "7 дней бесплатно · без карты",
        "hook": "разбор твоих сделок",
    }
    return defaults.get(kind, "")


def _badge_for(kind: str, text: str, metric: dict | None) -> str:
    low = text.lower()
    if "бесплатн" in low:
        return "0 ₽"
    if "4 884" in text or "4884" in text or "17" in text:
        return "−17%"
    if "490" in text:
        return "490 ₽/мес"
    if "7 дней" in low or "семь дней" in low:
        return "7 ДНЕЙ"
    if metric and metric.get("suffix") == "%":
        return "ЦИФРЫ"
    return ""


def make_plan(title: str, script: str, settings: dict) -> dict:
    sentences = split_sentences(script)
    if not sentences:
        raise ValueError("Сценарий пустой. Напиши хотя бы одно предложение.")

    target = None
    if str(settings.get("duration", "60")) not in ("auto", ""):
        try:
            target = float(settings["duration"])
        except Exception:
            target = None
    rate = int(settings.get("rate", 0))
    if settings.get("auto_rate", True):
        rate = suggest_rate(" ".join(sentences), target)

    # Duration of a scene in the final video is roughly 5.5-7 s.
    if target:
        scene_target = 5.4 + (target - 45) * 0.035
    else:
        scene_target = 6.0
    scene_chars = max(55, scene_target * 15.2 * (1 + rate / 100))
    # Hook should be a little shorter; CTA may hold longer.
    groups: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for s in sentences:
        estimated = len(s)
        if current and current_chars + estimated > scene_chars * 1.34:
            groups.append(current)
            current, current_chars = [], 0
        current.append(s)
        current_chars += estimated + 1
        if current_chars >= scene_chars:
            groups.append(current)
            current, current_chars = [], 0
    if current:
        groups.append(current)
    if len(groups) == 1 and len(sentences) >= 2:
        groups = [[s] for s in sentences]
    elif len(groups) < 3 and len(sentences) >= 3:
        groups = [[s] for s in sentences]
    if len(groups) > 1 and len(groups[0]) > 1 and len(groups[0][0]) < 55:
        # A very short first sentence (a hook) plays better alone.
        groups.insert(1, groups[0][1:])
        groups[0] = groups[0][:1]
    if len(groups) > 14:
        # Merge the shortest neighbouring groups instead of dropping text.
        while len(groups) > 14:
            idx = min(range(len(groups) - 1), key=lambda i: sum(len(x) for x in groups[i]) + sum(len(x) for x in groups[i + 1]))
            groups[idx] = groups[idx] + groups[idx + 1]
            del groups[idx + 1]

    total = len(groups)
    scenes: list[Scene] = []
    prev_kinds: list[str] = []
    for i, group in enumerate(groups):
        text = " ".join(group).strip()
        metric = extract_metric(text)
        bullets = make_bullets(text, 3, 36)
        kind = detect_type(text, i, total, prev_kinds, bool(metric), len(bullets) >= 2)
        # Trade-specific visuals only make sense with trading words.
        low = text.lower()
        if kind in ("dashboard", "chart", "terminal") and not any(
            w in low for w in ("сделк", "журнал", "график", "депозит", "прибыл",
                               "профит", "терминал", "стоп", "тейк", "фьючерс",
                               "позици", "ордер", "equity", "winrate", "просадк",
                               "r-мультипликатор", "сетап", "p&l")
        ):
            kind = "statement"
        ttl, accent = _scene_title(text, kind, title, i)
        note = _note_for(kind, text, metric)
        badge = _badge_for(kind, text, metric)
        scene = Scene(
            index=i,
            id=f"s{i + 1:02d}",
            kind=kind,
            text=text,
            title=ttl,
            accent=accent,
            kicker=TYPE_KICKERS.get(kind, "ГЛАВНОЕ"),
            note=note,
            badge=badge,
            bullets=bullets,
            metric=metric,
        )
        low = text.lower()
        if kind == "checklist":
            painful = any(w in low for w in ("теря", "ошибк", "слив", "проблем",
                                              "наруш", "минус", "боль", "хаос",
                                              "тильт", "переторг"))
            feature = any(w in low for w in ("детектор", "следит", "ловит", "можно",
                                              "бесплат", "клуб", "разбор", "контрол",
                                              "отчёт", "отчет", "приходит", "готов",
                                              "первые"))
            scene.tone = "bad" if painful and not feature else "good"
            scene.kicker = "ЧТО НЕ ТАК" if scene.tone == "bad" else "ЧТО ВНУТРИ"
        if "trade autopsy" in low and kind == "dashboard" and "TRADE AUTOPSY" not in scene.accent.upper():
            scene.accent = "TRADE AUTOPSY"
        if "smc" in low and "клуб" in low:
            scene.title = "ЗАКРЫТЫЙ КЛУБ"
            scene.accent = "SMC-РАЗБОРЫ 2-3 РАЗА В НЕДЕЛЮ"
            scene.note = "2–3 разбора в неделю"
        if "4 884" in text or "4884" in text:
            scene.note = "4 884 ₽/год · 407 ₽/мес · −17%"
        if kind == "chart":
            scene.chart = make_chart(text, seed=hash(text) & 0xFFFFFF)
        elif kind == "compare":
            scene.compare = make_compare(text)
        elif kind == "diagram":
            scene.diagram = make_diagram(text)
        elif kind == "dashboard":
            scene.rows = [list(r) for r in DASH_ROWS]
            scene.badge = "ПРИМЕР"
        elif kind == "bars":
            rng = random.Random(hash(text) & 0xFFFF)
            scene.rows = [[BAR_LABELS[j], round(rng.uniform(22, 78), 1)] for j in range(4)]
            scene.badge = "ПРИМЕР"
        elif kind == "terminal":
            scene.metric = scene.metric or {"value": 1.0842, "prefix": "", "suffix": "", "label": ""}
        elif kind == "stat" and metric is None:
            kind = "statement"
            scene.kind = kind
            scene.kicker = TYPE_KICKERS[kind]
        scene.est = max(3.2, estimate_seconds(text, rate) + 0.65)
        scenes.append(scene)
        prev_kinds.append(kind)

    # A one-line script still deserves a hook and a closing card.
    if len(scenes) == 1:
        scenes.append(Scene(
            index=1,
            id="s02",
            kind="cta",
            text="",
            title="НАЧНИ ВЕСТИ ЖУРНАЛ",
            accent="ССЫЛКА В ПРОФИЛЕ",
            kicker=TYPE_KICKERS["cta"],
            note="7 дней бесплатно · без карты",
            tone="",
            est=3.1,
        ))

    # A closing card only replaces content that is already a call to action.
    # Otherwise append a separate end card instead of pretending the last
    # sentence is a CTA.
    cta_words = ("начни", "начните", "ссылка", "перейд", "подпиш", "регистр",
                 "попроб", "забирай", "открыть", "жми", "пиши", "бесплат")
    if scenes and scenes[-1].kind != "cta":
        last_text = scenes[-1].text.lower()
        if any(w in last_text for w in cta_words):
            scenes[-1].kind = "cta"
            scenes[-1].kicker = TYPE_KICKERS["cta"]
            scenes[-1].note = "7 дней бесплатно · без карты"
        else:
            scenes.append(Scene(
                index=len(scenes),
                id=f"s{len(scenes) + 1:02d}",
                kind="cta",
                text="",
                title="НАЧНИ ВЕСТИ ЖУРНАЛ",
                accent="ССЫЛКА В ПРОФИЛЕ",
                kicker=TYPE_KICKERS["cta"],
                note="7 дней бесплатно · без карты",
                tone="",
                est=3.1,
            ))

    plan = {
        "title": title.strip() or "БЕЗ НАЗВАНИЯ",
        "scenes": [asdict(s) for s in scenes],
        "rate": rate,
        "target": target,
        "est_total": round(sum(s.est for s in scenes), 2),
        "style": settings.get("style", "tech_blue"),
    }
    return plan


# ---------------------------------------------------------------- subtitles
def make_caption_groups(scene: dict, max_chars: int = 30) -> list[list[dict]]:
    """Group word-boundary tokens into 2-3 line caption chunks."""
    words = scene.get("words") or []
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        piece = w.get("display") or w.get("w") or ""
        tentative = " ".join([(x.get("display") or x.get("w")) for x in cur] + [piece])
        if cur and (len(tentative) > max_chars or len(cur) >= 4):
            groups.append(cur)
            cur = []
        cur.append(w)
        if w.get("punct") and w.get("punct") in ".!?,":
            groups.append(cur)
            cur = []
    if cur:
        if groups and len(cur) == 1:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    # Never leave a lonely one-word caption when it can join the previous line.
    merged: list[list[dict]] = []
    for g in groups:
        if len(g) == 1 and merged:
            prev_len = len(" ".join(x.get("display") or x.get("w", "") for x in merged[-1]))
            add_len = len(g[0].get("display") or g[0].get("w", ""))
            if prev_len + add_len + 1 <= max_chars * 1.8:
                merged[-1].extend(g)
                continue
        merged.append(g)
    groups = merged

    # Keep 2 lines max by splitting long groups at a word boundary.
    out: list[list[dict]] = []
    for g in groups:
        if len(" ".join(x.get("display", x.get("w", "")) for x in g)) <= max_chars * 2:
            out.append(g)
            continue
        mid = max(1, len(g) // 2)
        out.append(g[:mid])
        out.append(g[mid:])
    return [g for g in out if g]
