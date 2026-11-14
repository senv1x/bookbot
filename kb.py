"""Answer engine: OpenAI (if OPENAI_API_KEY) grounded on scraped data, else rule-based intents + retrieval.

answer(data, message) -> {"answer", "booking": bool, "mode", "source"}
"""
import json, math, os, re, urllib.request

STOP = set("a an the is are am do does did you your yours we our i me my it its to of in on at for and or can could would "
           "should will what whats when where which who how there any have has with be this that please tell about if "
           "get got just like want need im i'm hi hello hey thanks thank".split())
SYN = {"cost": "price", "costs": "price", "fee": "price", "fees": "price", "charge": "price", "much": "price", "pricing": "price",
       "prices": "price", "hours": "open", "opening": "open", "times": "open", "close": "open", "closing": "open",
       "located": "address", "location": "address", "where": "address", "directions": "address", "find": "address",
       "number": "phone", "call": "phone", "ring": "phone", "telephone": "phone", "mobile": "phone",
       "appointment": "book", "appointments": "book", "booking": "book", "reserve": "book", "schedule": "book",
       "treatments": "service", "services": "service", "offer": "service", "lessons": "lesson", "tyre": "tyres"}
BOOK_RE = re.compile(r"\b(book|booking|appointment|appt|reserve|reservation|schedule|slot|availability|available|come in|"
                     r"sign me up|make an? (?:appt|appointment)|get an? (?:appt|appointment)|see (?:a|the) (?:dentist|vet|doctor))\b", re.I)
HOURS_RE = re.compile(r"\b(open|opening|hours|close|closing|closed|today|tomorrow|tonight|weekend|weekends|monday|tuesday|wednesday|"
                      r"thursday|friday|saturday|sunday|sat|sun|what time|when are you|bank holiday|christmas|evenings?)\b", re.I)
PHONE_RE = re.compile(r"\b(phone|call|number|ring|telephone|contact|whatsapp|text you|reach you|speak to)\b", re.I)
EMAIL_RE = re.compile(r"\b(e-?mail)\b", re.I)
ADDR_RE = re.compile(r"\b(where|address|located|location|directions|find you|parking|postcode|eircode|map)\b", re.I)
SERV_RE = re.compile(r"\b(services?|offer|treatments?|what (?:do|can) you|do you do|do you have|do you provide|lessons?|courses?)\b", re.I)
PRICE_RE = re.compile(r"\b(price|prices|cost|costs|how much|fee|fees|charge|quote|rates?|£|€|\$)", re.I)
GREET_RE = re.compile(r"^\s*(hi|hello|hey|good (?:morning|afternoon|evening)|hiya|yo)\b[\s!.,]*$", re.I)


DAY_IDX = {d: i for i, d in enumerate(["mo", "tu", "we", "th", "fr", "sa", "su"])}
FIRST_DAY = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
ADDON_RE = re.compile(r"\b(add(?:ed|-on)?|add on|extra(?!\s+large)|supplement|surcharge|additional|upgrade)\b|^\+|% off", re.I)


def order_hours(lines):
    """Stable sort of opening-hours lines Monday -> Sunday by the first weekday they mention (lines without a day go last)."""
    def key(x):
        m = FIRST_DAY.search(x[1])
        return (DAY_IDX[m.group(1)[:2].lower()] if m else 9, x[0])
    return [l for _, l in sorted(enumerate(lines), key=key)]


def tidy(text):
    """Remove doubled punctuation (but keep ellipses) and stray spaces before punctuation."""
    text = re.sub(r"(?<!\.)\.\s*\.(?!\.)", ".", text)
    text = re.sub(r"([,;:])\s*\1+", r"\1", text)
    text = re.sub(r"([£€$])\1+", r"\1", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return re.sub(r"\.\s*([.;])", ".", text)


def hours_text(d):
    return "; ".join(re.sub(r"^([A-Za-z\- –]+):(?=\S)", r"\1: ", re.sub(r"[.\s]+$", "", h)) for h in order_hours(d.get("hours", []))[:8])


def toks(text):
    out = []
    for w in re.findall(r"[a-z0-9£€$]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        w = SYN.get(w, w)
        for suf in ("ing", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _join(items, n=8):
    items = list(items)[:n]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _contact_line(d):
    bits = []
    if d.get("phones"):
        bits.append(f"call us on {d['phones'][0]}")
    if d.get("emails"):
        bits.append(f"email {d['emails'][0]}")
    return " or ".join(bits)


def _bm25(query, docs, k1=1.4, b=0.75):
    q = set(toks(query))
    if not q or not docs:
        return []
    dt = [toks(x) for x in docs]
    avg = sum(len(t) for t in dt) / len(dt) or 1
    df = {w: sum(1 for t in dt if w in t) for w in q}
    out = []
    for i, t in enumerate(dt):
        s = 0.0
        for w in q:
            f = t.count(w)
            if f:
                idf = math.log(1 + (len(dt) - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        if s:
            out.append((s, i, len(q & set(t)) / len(q)))
    return sorted(out, reverse=True)


def _sentences(text, n=2):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n])[:450]


def rule_answer(d, msg):
    name = d.get("name", "our business")
    m = msg.strip()
    contact = _contact_line(d)
    if not m:
        return {"answer": "Ask me anything about " + name + ".", "booking": False, "source": "empty"}
    if GREET_RE.match(m):
        return {"answer": f"Hi! I'm the virtual assistant for {name}. Ask me about services, opening hours or prices, or I can request a booking for you.",
                "booking": False, "source": "greeting"}
    q = set(toks(m))
    services = d.get("services", [])
    GENERIC = {"service", "offer", "price", "book", "lesson", "open", "phone", "address", "car", "dental", "hair", "treatment"}
    svc_hit = [s for s in services if (set(toks(s)) - GENERIC) & (q - GENERIC) and len(toks(s)) <= 6]

    if BOOK_RE.search(m) and not PRICE_RE.search(m) and not HOURS_RE.search(m.replace("available", "")):
        extra = f" for {svc_hit[0]}" if svc_hit else ""
        return {"answer": f"Happy to help you request an appointment{extra}. Pop your details in the form below and the team at {name} "
                          f"will confirm a time with you." + (f" If it's urgent, {contact}." if contact else ""),
                "booking": True, "source": "booking"}
    faq = _faq_match(d, m)
    # a price question should get a price: skip a matching FAQ whose answer has no amount in it
    if faq and faq[0] >= 0.6 and not (PRICE_RE.search(m) and not re.search(r"[£€$]\s*\d", faq[1]["a"])):
        return {"answer": faq[1]["a"], "booking": bool(BOOK_RE.search(m)), "source": "faq"}
    if PRICE_RE.search(m):
        pa = price_answer(d, q, contact)
        if pa:
            return pa
    if HOURS_RE.search(m) and not SERV_RE.search(m):
        if d.get("hours"):
            return {"answer": "Our opening hours: " + hours_text(d) + ". Outside these hours I can take a booking request for you.",
                    "booking": False, "source": "hours"}
        if d.get("hours_note"):
            return {"answer": d["hours_note"] + " Or leave your details below and we'll get back to you.", "booking": True, "source": "hours-note"}
        return {"answer": "I don't have our exact opening hours to hand." + (f" Please {contact}, or" if contact else "")
                          + " leave your details and we'll confirm.", "booking": True, "source": "hours-none"}
    if ADDR_RE.search(m) and d.get("address"):
        return {"answer": f"You'll find us at {d['address']}." + (f" Questions? {contact[0].upper() + contact[1:]}." if contact else ""),
                "booking": False, "source": "address"}
    if EMAIL_RE.search(m) and d.get("emails"):
        return {"answer": f"You can email us at {d['emails'][0]}.", "booking": False, "source": "contact"}
    if PHONE_RE.search(m) and (d.get("phones") or d.get("emails")):
        return {"answer": f"You can {contact}. Or leave your details here and we'll call you back.", "booking": False, "source": "contact"}
    if svc_hit:
        s = svc_hit[0]
        ranked = _bm25(m, [c["text"] for c in d.get("chunks", [])])
        more = _sentences(d["chunks"][ranked[0][1]]["text"]) if ranked and ranked[0][2] >= 0.5 else ""
        return {"answer": f"Yes, we offer {s}." + (f" {more}" if more else "") + " Would you like me to request a booking?",
                "booking": True, "source": "service"}
    content = q - {"service", "offer", "price", "do", "provide", "have", "any", "lesson", "book", "much", "you"}
    if content:
        base_prices = [p for p in d.get("prices", []) if not ADDON_RE.search(p)]
        for pool, label in ((base_prices, "price"), ([c["text"] for c in d.get("chunks", [])], "website")):
            ranked = _bm25(" ".join(content), pool)
            if ranked and ranked[0][2] >= 0.99 or (ranked and len(content) >= 3 and ranked[0][2] >= 0.66):
                hit = pool[ranked[0][1]]
                if label == "price":
                    return {"answer": f"Yes, our website lists: {hit}. Would you like to request a booking?", "booking": True, "source": "price-item"}
                if SERV_RE.search(m) or len(content) <= 2:
                    return {"answer": _sentences(hit), "booking": False, "source": "website"}
    if SERV_RE.search(m) and services:
        return {"answer": f"At {name} we offer {_join(services, 10)}. Would you like to request a booking?", "booking": False, "source": "services"}
    if faq and faq[0] >= 0.34:
        return {"answer": faq[1]["a"], "booking": False, "source": "faq"}
    chunks = d.get("chunks", [])
    ranked = _bm25(m, [c["text"] for c in chunks])
    if ranked and ranked[0][2] >= 0.5 and ranked[0][0] > 1.0:
        return {"answer": _sentences(chunks[ranked[0][1]]["text"]), "booking": False, "source": "website"}
    return {"answer": f"I'm not sure about that one, but the team at {name} can help." + (f" You can {contact}, or" if contact else "")
                      + " leave your name and number below and they'll get back to you.", "booking": True, "source": "handoff"}


FAQ_GENERIC = {"service", "offer", "price", "open", "phone", "address", "book", "do", "provide"}


def _split_price(line):
    return line.split(" – ", 1) if " – " in line else ("", line)


def price_answer(d, q, contact):
    prices = d.get("prices", [])
    mm = re.match(r"https?://[^/]+", d.get("website", ""))
    root = mm.group(0) + "/" if mm else ""
    site = root
    content = q - {"price", "much", "service", "book", "do", "have", "provide", "offer", "you", "ll", "cost"}
    if not prices:
        return {"answer": "Prices depend on what you need, so the team will give you an exact quote." + (f" You can {contact}," if contact else "")
                          + " or leave your details below and we'll get back to you.", "booking": True, "source": "prices-none"}
    if content:
        wants_addon = bool(content & {"add", "extra", "addon", "supplement"})
        scored = []
        for i, line in enumerate(prices):
            head, rest = _split_price(line)
            ht, rt = set(toks(head)), set(toks(rest))
            # loose stem match: "shave" ~ "shav(ing)", "crown" ~ "crowns"
            near = lambda pool: {c for c in content if any(c == t or (min(len(c), len(t)) >= 4 and (c.startswith(t) or t.startswith(c))) for t in pool)}
            ht, rt = near(ht), near(rt)
            cov = len(ht | rt) / len(content)
            if cov < (1.0 if len(content) <= 2 else 0.66):
                continue
            s = 2 * len(ht) + len(rt - ht)
            if s and ADDON_RE.search(line) and not wants_addon:
                s *= 0.3  # "£10 added to full groom" must not beat the Full Groom price itself
            if s:
                scored.append((s, i))
        if scored:
            best = max(s for s, _ in scored)
            hits = [prices[i] for s, i in sorted(scored, key=lambda x: x[1]) if s == best]
            heads = {_split_price(h)[0] for h in hits}
            if len(heads) == 1 and next(iter(heads)) and len(hits) > 1:
                head = next(iter(heads))
                items = [_split_price(h)[1] for h in hits][:8]
                tiered = sum(1 for x in items if re.match(r"(toy|small|medium|large|extra large|giant|gigantic)\b", x, re.I)) >= 2
                who = "your dog's size" if re.search(r"\bdog|groom|\bpet", " ".join(d.get("services", [])) + d.get("name", ""), re.I) else "size"
                lead = f"{head} prices depend on {who}: " if tiered else f"{head}: "
                return {"answer": tidy(lead + "; ".join(items) + "." + (f" Full details are on our website: {site}" if tiered and site else "")
                                       + " Would you like to request a booking?"), "booking": False, "source": "price-item"}
            return {"answer": tidy("Here's what our website lists: " + "; ".join(hits[:4]) + ". Want me to request a booking?"),
                    "booking": False, "source": "prices"}
        if content - {"how", "what", "is", "are", "the", "for", "a"}:
            return {"answer": tidy("I don't have a listed price for that." + (f" Our prices are on our website ({root})," if root else "")
                                   + (f" or you can {contact}," if contact else "") + " or leave your details below and we'll get back to you."),
                    "booking": True, "source": "prices-unlisted"}
    base = [p for p in prices if not ADDON_RE.search(p) and re.match(r"[A-Z0-9]", p)] or prices  # skip fragments like "(Normally £12) and..."
    return {"answer": tidy("Some of our prices: " + "; ".join(base[:5]) + ". For an exact quote, leave your details and we'll get back to you."),
            "booking": False, "source": "prices"}


def _faq_match(d, m):
    faqs = d.get("faqs", [])
    if not faqs:
        return None
    q = set(toks(m))
    if not (q - FAQ_GENERIC):
        return None  # generic question ("what services do you offer?") -> handled by intents
    ranked = _bm25(" ".join(q - FAQ_GENERIC), [f["q"] for f in faqs])
    if not ranked:
        return None
    s, i, cov = ranked[0]
    return cov, faqs[i]


def context(d, msg, n=6):
    lines = [f"Business: {d.get('name')}", f"Website: {d.get('website', '')}"]
    for k, label in (("description", "About"), ("address", "Address")):
        if d.get(k):
            lines.append(f"{label}: {d[k]}")
    for k, label in (("phones", "Phone"), ("emails", "Email"), ("hours", "Opening hours"), ("services", "Services"), ("prices", "Prices")):
        if d.get(k):
            lines.append(f"{label}: " + "; ".join(d[k][:20]))
    for f in d.get("faqs", [])[:12]:
        lines.append(f"FAQ: {f['q']} -> {f['a']}")
    chunks = d.get("chunks", [])
    for s, i, cov in _bm25(msg, [c["text"] for c in chunks])[:n]:
        lines.append("Website text: " + chunks[i]["text"])
    return "\n".join(lines)


def openai_answer(d, msg, history=None):
    system = ("You are the friendly front-desk assistant on the website of a small business. Answer ONLY from the business info below; "
              "never invent prices, hours, services or policies. If the info doesn't cover the question, say you're not sure and offer to take "
              "their details so the team can get back to them. You cannot confirm appointments yourself: you collect a booking request "
              "(name, phone, service, preferred time) that the team confirms. When the visitor wants to book, or should leave details, "
              "end your reply with the token [BOOKING]. Keep replies under 70 words, reply in the visitor's language.\n\n" + context(d, msg))
    msgs = [{"role": "system", "content": system}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:800]})
    msgs.append({"role": "user", "content": msg})
    body = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2, "messages": msgs}
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"})
    text = json.load(urllib.request.urlopen(req, timeout=25))["choices"][0]["message"]["content"].strip()
    booking = "[BOOKING]" in text
    return {"answer": text.replace("[BOOKING]", "").strip(), "booking": booking or bool(BOOK_RE.search(msg)), "source": "openai"}


def answer(d, msg, history=None):
    msg = (msg or "")[:1000]
    if os.getenv("OPENAI_API_KEY"):
        try:
            r = openai_answer(d, msg, history); r["mode"] = "openai"; return r
        except Exception as e:
            print("LLM error, falling back to rules:", e)
    r = rule_answer(d, msg); r["answer"] = tidy(r["answer"]); r["mode"] = "rules"; return r
