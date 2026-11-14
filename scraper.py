"""Website scraper: turns a small-business site into structured assistant data in ~5-20 s.

scrape(url) -> {"ok", "data": {...}, "quality", "notes", "pages"}
data = {name, description, website, phones, emails, address, hours[], services[], prices[], faqs[{q,a}], chunks[]}
"""
import ipaddress, json, os, re, socket, string, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 BookBot/1.0")
MAX_PAGES = int(os.getenv("SCRAPE_MAX_PAGES", "8"))
TIMEOUT = float(os.getenv("SCRAPE_TIMEOUT", "10"))
MAX_BYTES = 3_000_000

DAYS = r"(?:mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)(?:day|nesday|sday|urday|rsday)?|weekdays?|weekends?|bank holidays?"
TIME = r"(?:\d{1,2}[:.]\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|closed|noon|midday|24\s*hours|by appointment)"
DAY_RE = re.compile(rf"\b(?:{DAYS})\b", re.I)
TIME_RE = re.compile(TIME, re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}")
PRICE_RE = re.compile(r"[£€$]\s?\d+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?\s?(?:EUR|GBP|USD)\b")
POSTCODE_RE = re.compile(r"\b(?:[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|[AC-FHKNPRTV-Y]\d{2}\s?[AC-FHKNPRTV-Y\d]{4}|[A-Z]{2}\s\d{5}(?:-\d{4})?)\b")
LINK_WEIGHTS = [("contact", 6), ("service", 6), ("treatment", 6), ("price", 6), ("pricing", 6), ("fees", 5), ("faq", 6),
                ("question", 4), ("lesson", 5), ("course", 4), ("menu", 3), ("hour", 5), ("opening", 5), ("book", 4),
                ("appointment", 4), ("about", 3), ("mot", 4), ("repair", 4), ("groom", 4), ("hair", 3), ("team", 1),
                ("location", 3), ("visit", 2), ("find-us", 4), ("new-patient", 4), ("patients", 3)]
SKIP_LINK = re.compile(r"\.(?:pdf|jpe?g|png|gif|webp|svg|zip|docx?|xlsx?|mp4|mp3)$|/wp-(?:admin|login)|/cart|/checkout|/login|/account|"
                       r"/feed|/tag/|/author/|/category/|privacy|cookie|terms|sitemap|/blog/.+|/news/.+", re.I)
JUNK = re.compile(r"^(?:home|about(?: us)?|contact(?: us)?|menu|privacy.*|cookie.*|terms.*|log ?in|sign ?up|blog|news|read more|"
                  r"learn more|more info|find out more|click here|book now|book online|call now|get in touch|follow us.*|share|"
                  r"search|skip to.*|close|next|previous|back|our services|services|gallery|testimonials?|reviews?|faqs?|"
                  r"prices|price list|pricing|opening hours|opening times|hours|location|address|phone|email|team|meet the team|careers|sitemap|"
                  r"accessibility|copyright.*|all rights reserved.*|facebook|instagram|twitter|linkedin|youtube|tiktok|x|"
                  r"get directions|directions|map|view more|see more|submit|send|send message|call us|welcome.*|"
                  r"quick links|useful links|links|information|info|connect with us|social|newsletter|subscribe)$", re.I)
SERVICE_PAGE = re.compile(r"service|treatment|price|pricing|fee|lesson|course|menu|repair|mot|groom|hair|what-we-do|offer|package", re.I)


class ScrapeBlocked(Exception):
    pass


def _host_ok(host):
    if os.getenv("ALLOW_PRIVATE_SCRAPE") == "1":
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ScrapeBlocked(f"could not resolve {host}")
    allow = [ipaddress.ip_network(n.strip()) for n in os.getenv("SCRAPE_ALLOW_NETS", "").split(",") if n.strip()]
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in n for n in allow):
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ScrapeBlocked("private or local addresses are not allowed")
    return True


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("Please enter your website address.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    if not p.hostname or "." not in p.hostname:
        raise ValueError("That doesn't look like a website address.")
    return url


CHALLENGE = re.compile(r"<title>\s*(?:one moment, please|just a moment|attention required|checking your browser|please wait|ddos-guard)", re.I)
ALT_UAS = ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"]


def _fetch(url, timeout=None):
    final, html = _fetch_once(url, timeout, UA)
    for ua in ALT_UAS:
        if not CHALLENGE.search(html[:5000]):
            break
        time.sleep(1.5)
        final, html = _fetch_once(url, timeout, ua)
    if CHALLENGE.search(html[:5000]):
        raise RuntimeError("site shows a bot-protection page")
    return final, html


def _fetch_once(url, timeout, ua):
    p = urllib.parse.urlparse(url)
    _host_ok(p.hostname)
    h = {"User-Agent": ua, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-GB,en;q=0.9"}
    try:
        r = requests.get(url, headers=h, timeout=timeout or TIMEOUT, allow_redirects=True, stream=True)
    except requests.exceptions.SSLError:
        r = requests.get(url, headers=h, timeout=timeout or TIMEOUT, allow_redirects=True, stream=True, verify=False)
    _host_ok(urllib.parse.urlparse(r.url).hostname)
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    if "html" not in ctype and ctype:
        raise RuntimeError(f"not an HTML page ({ctype.split(';')[0]})")
    body = r.raw.read(MAX_BYTES, decode_content=True)
    enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
    try:
        html = body.decode(enc or "utf-8", errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    return r.url, html


def _clean(t):
    return re.sub(r"\s+", " ", re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", t or "")).strip()


def _host(u):
    return (urllib.parse.urlparse(u).hostname or "").lower().removeprefix("www.")


def _jsonld(soup):
    out = []
    for s in soup.find_all("script", type=lambda v: v and "ld+json" in v.lower()):
        try:
            d = json.loads(s.string or s.get_text() or "")
        except Exception:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                for k in ("@graph", "mainEntity", "itemListElement", "hasOfferCatalog", "makesOffer", "itemOffered"):
                    if k in x:
                        stack.append(x[k])
    return out


def _types(x):
    t = x.get("@type", "")
    return [t] if isinstance(t, str) else [str(i) for i in t] if isinstance(t, list) else []


def _fmt_address(a):
    if isinstance(a, str):
        return re.sub(r"(,\s*)+", ", ", _clean(a)).strip(", ")
    if isinstance(a, dict):
        parts = [a.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
        return ", ".join(_clean(str(p)).strip(", ") for p in parts if p and _clean(str(p)).strip(", "))
    return ""


def _phone_ok(p):
    digits = re.sub(r"\D", "", p)
    if not 9 <= len(digits) <= 15:
        return False
    if re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
        return False
    return not re.fullmatch(r"\d{4}[-.]\d{2}[-.]\d{2}", p.strip())


def _add(lst, item, limit):
    item = _clean(item)
    if item and item.lower() not in {x.lower() for x in lst} and len(lst) < limit:
        lst.append(item)


def _parse(url, html, acc, is_service_page):
    soup = BeautifulSoup(html, "html.parser")
    for x in _jsonld(soup):
        ts = [t.lower() for t in _types(x)]
        if any(t in ("faqpage",) for t in ts):
            pass
        if "question" in ts:
            q = _clean(x.get("name") or x.get("text"))
            ans = x.get("acceptedAnswer") or {}
            if isinstance(ans, list):
                ans = ans[0] if ans else {}
            a = _clean(BeautifulSoup(str(ans.get("text", "")), "html.parser").get_text(" "))
            if q and a:
                acc["faqs"].append({"q": q, "a": a[:600]})
        if any(t in ("localbusiness", "organization", "dentist", "medicalbusiness", "autorepair", "beautysalon", "hairsalon",
                     "healthandbeautybusiness", "automotivebusiness", "store", "professionalservice", "medicalclinic",
                     "physician", "veterinarycare", "educationalorganization", "drivingschool", "dayspa", "accountingservice")
               or t.endswith("business") for t in ts):
            if x.get("name") and not acc["ld_name"]:
                acc["ld_name"] = _clean(str(x["name"]))
            if x.get("telephone"):
                _add(acc["phones"], str(x["telephone"]), 4)
            if x.get("email"):
                _add(acc["emails"], str(x["email"]).replace("mailto:", ""), 4)
            if x.get("address") and not acc["address"]:
                acc["address"] = _fmt_address(x["address"])
            oh = x.get("openingHours")
            if oh:
                for line in (oh if isinstance(oh, list) else [oh]):
                    _add(acc["hours"], str(line), 12)
            for spec in (x.get("openingHoursSpecification") or []):
                if isinstance(spec, dict):
                    days = spec.get("dayOfWeek", "")
                    days = ", ".join(str(d).split("/")[-1] for d in (days if isinstance(days, list) else [days]))
                    if spec.get("opens") and spec.get("closes"):
                        _add(acc["hours"], f"{days}: {spec['opens'][:5]}-{spec['closes'][:5]}", 12)
        if any(t in ("service", "offer", "product") for t in ts):
            n = x.get("name") or (x.get("itemOffered") or {}).get("name") if isinstance(x.get("itemOffered"), dict) else x.get("name")
            if n:
                _add(acc["services"], str(n), 25)

    if not acc["og_name"]:
        m = soup.find("meta", property="og:site_name")
        if m and m.get("content"):
            acc["og_name"] = _clean(m["content"])
    if not acc["title"] and soup.title:
        acc["title"] = _clean(soup.title.get_text())
    if not acc["description"]:
        m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if m and m.get("content"):
            acc["description"] = _clean(m["content"])[:300]

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            p = urllib.parse.unquote(href[4:]).strip()
            if _phone_ok(p):
                _add(acc["phones"], p, 4)
        elif href.lower().startswith("mailto:"):
            e = urllib.parse.unquote(href[7:]).split("?")[0].strip()
            if EMAIL_RE.fullmatch(e):
                _add(acc["emails"], e, 4)
        else:
            full = urllib.parse.urljoin(url, href).split("#")[0]
            if full.startswith("http") and _host(full) == acc["host"] and not SKIP_LINK.search(urllib.parse.urlparse(full).path):
                text = (_clean(a.get_text()) + " " + full).lower()
                score = sum(w for k, w in LINK_WEIGHTS if k in text)
                if score:
                    acc["links"][full] = max(acc["links"].get(full, 0), score)

    # FAQ: <details><summary>, and headings / bold lines ending with '?'
    for d in soup.find_all("details"):
        s = d.find("summary")
        if s:
            q = _clean(s.get_text(" "))
            a = _clean(d.get_text(" ").replace(s.get_text(" "), "", 1))
            if q and a and len(acc["faqs"]) < 30:
                acc["faqs"].append({"q": q[:200], "a": a[:600]})

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template", "form", "select", "button"]):
        tag.decompose()

    for h in soup.find_all(["h2", "h3", "h4", "h5", "dt", "strong", "b", "button"]):
        q = _clean(h.get_text(" "))
        if q.endswith("?") and 8 < len(q) < 200:
            parts = []
            for sib in h.find_all_next(True, limit=8):
                if sib.name in ("h1", "h2", "h3", "h4", "h5", "dt") or (sib.name in ("strong", "b") and _clean(sib.get_text()).endswith("?")):
                    break
                if sib.name in ("p", "dd", "li", "div") and not sib.find(["p", "div", "li"]):
                    t = _clean(sib.get_text(" "))
                    if t and t != q:
                        parts.append(t)
                if sum(len(x) for x in parts) > 400:
                    break
            a = " ".join(parts)[:600]
            if a and len(acc["faqs"]) < 30 and q.lower() not in {f["q"].lower() for f in acc["faqs"]}:
                acc["faqs"].append({"q": q, "a": a})

    # Services: headings + list items in content (not nav/header/footer)
    for nav in soup.find_all(["nav", "header", "footer"]):
        nav_text = nav.get_text("\n")
        acc["chrome_text"].append(nav_text)
        nav.decompose()
    cand = soup.find_all(["h2", "h3", "h4"]) + (soup.find_all("li") if is_service_page else [])
    for el in cand:
        t = _clean(el.get_text(" "))
        t = re.sub(r"\s*[-–:|]\s*[£€$]\s?\d.*$", "", t).strip(" -–:|•·")
        if (3 <= len(t) <= 60 and len(t.split()) <= 7 and "?" not in t and not JUNK.match(t) and not EMAIL_RE.search(t)
                and not PHONE_RE.search(t) and not DAY_RE.search(t) and sum(c.isdigit() for c in t) <= 3
                and not re.search(r"©|cookie|\bwe\b|\byou\b|\bour\b|\bus\b|welcome|why choose|testimonial|review", t, re.I)):
            (acc["services_strong"] if is_service_page else acc["services_weak"]).append(t)

    text = soup.get_text("\n")
    lines = [_clean(l) for l in text.split("\n")]
    lines = [l for l in lines if l]
    full_lines = lines + [_clean(l) for t in acc["chrome_text"][-3:] for l in t.split("\n") if _clean(l)]
    # table layouts: a column of days followed by a column of times
    i = 0
    while i < len(full_lines):
        j = i
        while j < len(full_lines) and len(full_lines[j]) < 25 and DAY_RE.search(full_lines[j]) and not TIME_RE.search(full_lines[j]):
            j += 1
        k = j - i
        if k >= 3 and all(j + n < len(full_lines) and TIME_RE.search(full_lines[j + n]) and len(full_lines[j + n]) < 40
                          and not DAY_RE.search(full_lines[j + n]) for n in range(k)):
            for n in range(k):
                _add(acc["hours"], f"{full_lines[i + n].rstrip(':')}: {full_lines[j + n]}", 16)
            i = j + k
        else:
            i = max(j, i + 1)
    for i, l in enumerate(full_lines):
        if len(l) <= 140 and DAY_RE.search(l):
            if TIME_RE.search(l):
                _add(acc["hours"], l, 16)
            elif not any(h.lower().startswith(l.lower().rstrip(":").strip()) for h in acc["hours"]) and i + 1 < len(full_lines) and TIME_RE.search(full_lines[i + 1]) and len(full_lines[i + 1]) < 40 and not DAY_RE.search(full_lines[i + 1]):
                _add(acc["hours"], f"{l} {full_lines[i + 1]}", 16)
        if PRICE_RE.search(l) and 4 < len(l) <= 120:
            prev = full_lines[i - 1] if i and len(full_lines[i - 1]) < 60 and not PRICE_RE.search(full_lines[i - 1]) else ""
            _add(acc["prices"], (prev + " " + l).strip() if len(l) < 15 and prev else l, 30)
        if not acc["address_guess"] and POSTCODE_RE.search(l) and len(l) < 160:
            acc["address_guess"] = l if len(l) > 15 or i == 0 else f"{full_lines[i - 1]}, {l}"
        if len(acc["phones"]) < 2:
            for m in PHONE_RE.finditer(l):
                if _phone_ok(m.group()) and re.search(r"tel|phone|call|ring|mob|\+|^\(?0", l, re.I):
                    _add(acc["phones"], m.group().strip(), 4)
        for m in EMAIL_RE.finditer(l):
            e = m.group()
            if not re.search(r"\.(png|jpe?g|gif|webp|svg)$|sentry|wixpress|example\.|domain\.com|@2x", e, re.I):
                _add(acc["emails"], e, 4)
    for p in soup.find_all(["p", "li", "td", "dd"]):
        t = _clean(p.get_text(" "))
        if 40 <= len(t) <= 700 and t not in acc["chunk_set"]:
            acc["chunk_set"].add(t); acc["chunks"].append({"text": t, "url": url})
    return soup


def _pick_name(acc, url):
    for t in (acc["ld_name"], acc["og_name"], acc["title"]):
        n = _name_from(t)
        if n:
            return n
    h = _host(url).split(".")[0]
    return re.sub(r"[-_]", " ", h).title()


def _name_from(t):
    t = t or ""
    t = re.sub(r"^(?:welcome to|call (?:the )?[\w\s]{0,30}? at|contact(?: us)?(?: at)?|visit)\s+", "", t.strip(), flags=re.I)
    t = re.sub(r"\s+(?:in|near)\s+[A-Z][\w']+(?:\s[A-Z][\w']+)?$", "", t)
    segs = [s.strip() for s in re.split(r"\s[|–—\-:·]\s|\s\|\s?|\|", t) if s.strip()]
    generic = re.compile(r"^(home|homepage|welcome.*|contact.*|services?|about.*|book.*|index|page \d+)$", re.I)
    segs = [s for s in segs if not generic.match(s) and len(s) < 70]
    if segs:
        segs.sort(key=lambda s: (bool(re.search(r"\b(in|near|for|best|top|affordable)\b", s, re.I)), len(s) > 40))
        return segs[0]
    return ""


VOCAB = [  # (regex, display) fallback service detection across verticals
    (r"check-?ups?|dental exam", "Check-ups"), (r"hygien(?:e|ist)|scale (?:and|&) polish", "Hygiene / scale & polish"),
    (r"teeth whitening|whitening", "Teeth whitening"), (r"implants?", "Dental implants"), (r"invisalign|braces|orthodont", "Orthodontics"),
    (r"root canal", "Root canal treatment"), (r"crowns?\b", "Crowns"), (r"veneers?", "Veneers"), (r"dentures?", "Dentures"),
    (r"extractions?", "Extractions"), (r"emergency (?:dental|appointment)", "Emergency appointments"),
    (r"\bmots?\b", "MOT testing"), (r"servic(?:e|ing) (?:your )?(?:car|vehicle)|car servic|full service|interim service", "Car servicing"),
    (r"tyres?|tires?", "Tyres"), (r"brakes?", "Brakes"), (r"diagnostics?", "Diagnostics"), (r"exhausts?", "Exhausts"),
    (r"batter(?:y|ies)", "Batteries"), (r"clutch", "Clutch repair"), (r"air ?con", "Air conditioning"), (r"wheel alignment|tracking", "Wheel alignment"),
    (r"bodywork|accident repair", "Bodywork / accident repair"), (r"driving lessons?", "Driving lessons"),
    (r"intensive (?:course|lessons?)", "Intensive courses"), (r"pass ?plus", "Pass Plus"), (r"\bedt\b|essential driver training", "EDT lessons"),
    (r"pre-?test", "Pre-test lessons"), (r"test car|car for (?:the )?test", "Car for test"), (r"refresher", "Refresher lessons"),
    (r"automatic (?:lessons?|car)", "Automatic lessons"), (r"haircuts?|cut (?:and|&) (?:blow|finish)", "Haircuts"),
    (r"colou?r(?:ing)?\b|highlights|balayage", "Colouring / highlights"), (r"blow ?dry", "Blow dry"), (r"barber|beard trim|fade", "Barbering"),
    (r"perms?\b", "Perms"), (r"wedding hair|bridal", "Bridal hair"), (r"dog groom|full groom|grooming", "Dog grooming"),
    (r"bath (?:and|&) brush|bath and dry", "Bath & brush"), (r"nail clipping|nail trim", "Nail clipping"), (r"puppy", "Puppy appointments"),
    (r"physiotherap|physio\b", "Physiotherapy"), (r"sports massage|massage", "Massage"), (r"osteopath", "Osteopathy"),
    (r"home visits?", "Home visits"), (r"acupuncture|dry needling", "Acupuncture / dry needling"), (r"vaccinations?", "Vaccinations"),
    (r"neuter|spay", "Neutering"), (r"microchip", "Microchipping"), (r"consultations?", "Consultations"),
    (r"bookkeeping", "Bookkeeping"), (r"tax returns?", "Tax returns"), (r"payroll", "Payroll"), (r"vat\b", "VAT returns"),
    (r"cleaning service|deep clean|end of tenancy", "Cleaning"),
]


def _vocab_services(acc):
    text = " ".join(c["text"] for c in acc["chunks"]) + " " + acc["description"] + " " + " ".join(acc["services_weak"])
    found = []
    for rx, label in VOCAB:
        if re.search(rf"\b(?:{rx})", text, re.I):
            found.append(label)
    return found


def _dedupe_phones(phones):
    out, seen = [], {}
    for p in phones:
        k = re.sub(r"\D", "", p)[-9:]
        nice = len(re.findall(r"[\s()-]", p))
        if k in seen:
            i = seen[k]
            if nice > len(re.findall(r"[\s()-]", out[i])):
                out[i] = p
        else:
            seen[k] = len(out); out.append(p)
    return [re.sub(r"^\+\s+", "+", p) for p in out]


def _clean_hours(lines):
    text_style = [l for l in lines if not re.match(r"^(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:[\s,\-]|$)", l)]
    lines = text_style if len(text_style) >= 2 else lines
    out, seen = [], set()
    for l in lines:
        l = l.strip(" ,;")
        if len(l) > 90:
            continue
        k = re.sub(r"[^a-z0-9]", "", l.lower().replace("day", "").replace(".", ":"))
        if k in seen:
            continue
        seen.add(k); out.append(l)
    return out[:10]


def _finalize_services(acc):
    out = []
    pools = acc["services"] + acc["services_strong"]
    if len(pools) < 3:
        pools += acc["services_weak"]
    counts = {}
    for s in pools:
        counts[s.lower()] = counts.get(s.lower(), 0) + 1
    vocab_rx = re.compile("|".join(rx for rx, _ in VOCAB), re.I)
    name_words = {w for w in re.findall(r"[a-z]{3,}", acc.get("name", "").lower())} - {"the", "and", "car", "dental", "hair", "driving"}
    for s in pools:
        if counts[s.lower()] > 4 and s not in acc["services"]:
            continue  # repeated boilerplate
        sw = set(re.findall(r"[a-z]{3,}", s.lower()))
        if s.lower() == acc.get("name", "").lower() or (name_words and len(sw & name_words) >= max(1, len(name_words) // 2)):
            continue
        if re.search(r"[.!]$|^[£€$\d]|/hr\b|\b(?:journey|smarter|confidence|today|save|start|calm|clear|progress|packages?|payments?|"
                     r"flexible|personali[sz]ed|quality|professional|friendly|experienced|trusted|why|how|get|your|book|call|"
                     r"compared|options|hours of|minute)\b", s, re.I):
            continue
        if (re.search(r"\bdr\.?\s|\b(?:dentist|hygienist|nurse|manager|receptionist|owner|instructor|director|partner|associate)$|/|"
                     r"philosophy|cancellation|policy|polic|equipment|expertise|customer|evaluate|identify|ensure|hazard|condition|"
                     r"feedback|recommendation|comprehensive|modern|extended|ideal for|better value|required|selection|"
                     r"\bvs\b|insurance|finance|parking|testimonial|gallery|portfolio|vacanc|join|newsletter|covid|"
                     r"^(?:implement|remove|eliminate|follow|operating|latest|news|qualification|expert|safety|fast track|student|"
                     r"success|location|appointments?$|treatment cost|suitability|definitive|meet|map|area|region|central|north|south|east|west)|"
                     r"\bm\.?ost\b|\bbds\b|\bmsc\b|\bbsc\b|\bgdc\b|manchester$|london$", s, re.I)
                or re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", s) and not vocab_rx.search(s) and not re.search(r"(?:ing|ment|ion|ure|s)$", s.split()[-1])
                or re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", s)
                or (len(s.split()) == 1 and not vocab_rx.search(s) and len(s) < 7)):
            continue
        if re.search(r"\bservices$", s, re.I) and len(s.split()) > 2:
            continue
        if re.search(r"\babout\b|\bltd\b|\blimited\b|\bpractice$|^our |\bsurgery$|\bclinic$|\bcontact|\bopening|\bwhat we\b", s, re.I):
            continue
        _add(out, string.capwords(s.lower()) if s.isupper() else s, 15)
    out.sort(key=lambda s: not vocab_rx.search(s))
    out = out[:10]
    if len(out) < 4:
        for v in _vocab_services(acc):
            if not any(v.split()[0].lower() in o.lower() for o in out):
                _add(out, v, 15)
    return out


def scrape(url, budget=18.0, workers=3, page_timeout=7):
    t0 = time.time()
    url = normalize_url(url)
    acc = {"host": _host(url), "ld_name": "", "og_name": "", "title": "", "description": "", "phones": [], "emails": [],
           "address": "", "address_guess": "", "hours": [], "services": [], "services_strong": [], "services_weak": [],
           "prices": [], "faqs": [], "chunks": [], "chunk_set": set(), "links": {}, "chrome_text": []}
    notes, pages = [], []
    try:
        final, html = _fetch(url)
    except ScrapeBlocked as e:
        return {"ok": False, "error": str(e), "data": {"website": url}, "quality": "failed", "notes": str(e), "pages": []}
    except Exception as e:
        root = f"{urllib.parse.urlparse(url).scheme}://{urllib.parse.urlparse(url).netloc}/"
        try:
            if root.rstrip("/") == url.rstrip("/"):
                raise
            final, html = _fetch(root)
            notes.append(f"start page failed ({e}), used homepage")
        except Exception as e2:
            msg = f"Could not open the website ({type(e2).__name__}: {str(e2)[:120]})"
            return {"ok": False, "error": msg, "data": {"website": url}, "quality": "failed", "notes": msg, "pages": []}
    acc["host"] = _host(final)
    pages.append(final)
    _parse(final, html, acc, bool(SERVICE_PAGE.search(urllib.parse.urlparse(final).path)))
    root = f"{urllib.parse.urlparse(final).scheme}://{urllib.parse.urlparse(final).netloc}/"
    queue = []
    if root.rstrip("/") != final.rstrip("/"):
        queue.append(root)
    queue += [u for u, _ in sorted(acc["links"].items(), key=lambda kv: -kv[1]) if u.rstrip("/") not in (final.rstrip("/"), root.rstrip("/"))]
    queue = queue[:MAX_PAGES - 1]

    def get(u):
        if time.time() - t0 > budget:
            return u, None, "time budget"
        try:
            return (*_fetch(u, timeout=min(page_timeout, max(2, budget - (time.time() - t0)))), None)
        except Exception as e:
            return u, None, str(e)[:80]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(get, queue))
    for u, html2, err in results:
        if html2 is None:
            if err:
                notes.append(f"skipped {urllib.parse.urlparse(u).path or '/'}: {err}")
            continue
        pages.append(u)
        _parse(u, html2, acc, bool(SERVICE_PAGE.search(urllib.parse.urlparse(u).path)))

    name = _pick_name(acc, final)
    acc["name"] = name
    data = {
        "name": name, "website": final, "description": acc["description"],
        "phones": _dedupe_phones(acc["phones"])[:3], "emails": acc["emails"][:3],
        "address": re.sub(r"(,\s*)+", ", ", acc["address"] or acc["address_guess"]).strip(", ."), "hours": _clean_hours(acc["hours"]),
        "services": _finalize_services(acc), "prices": acc["prices"][:20], "faqs": acc["faqs"][:20],
        "chunks": acc["chunks"][:250],
    }
    q, qnotes = assess(data)
    return {"ok": True, "data": data, "quality": q, "notes": "; ".join(qnotes + notes[:4]), "pages": pages,
            "seconds": round(time.time() - t0, 1)}


def assess(d):
    got, missing = [], []
    for key, label in (("phones", "phone"), ("emails", "email"), ("address", "address"), ("hours", "hours"),
                       ("services", "services"), ("faqs", "FAQ"), ("prices", "prices")):
        (got if d.get(key) else missing).append(label)
    score = sum(1 for k in ("phones", "address", "hours") if d.get(k)) + (2 if len(d.get("services", [])) >= 3 else 0) \
        + (1 if d.get("faqs") else 0) + (1 if len(d.get("chunks", [])) >= 10 else 0) + (1 if d.get("emails") else 0)
    q = "good" if score >= 6 else "partial" if score >= 3 else "poor"
    notes = [f"found: {', '.join(got) or 'nothing structured'}"]
    if missing:
        notes.append(f"missing: {', '.join(missing)}")
    return q, notes
