"""BookBot server (Python 3.10+, stdlib http.server + SQLite; requests/bs4 for scraping).

Pages:  /  landing+onboarding · /demo/<slug> public demo · /dashboard/<slug>?key= · /edit/<slug>?key= · /admin?token=
API:    POST /api/onboard {url, owner_email?} · GET /api/bot/<slug> · POST /api/chat {bot,message,history}
        POST /api/booking {bot,name,phone,service,preferred_time,note} · POST /api/setup-request · GET /healthz
"""
import json, os, re, secrets, threading, time, unicodedata, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


def load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()
import store, scraper, kb, notify, pages  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
SETUP_TO = os.getenv("SETUP_REQUEST_TO", "shipfastlabs.dev@gmail.com")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_hits, _lock = {}, threading.Lock()
LIMITS = {"onboard": (int(os.getenv("RATE_ONBOARD_PER_HOUR", "20")), 3600), "chat": (int(os.getenv("RATE_CHAT_PER_MIN", "40")), 60), "booking": (10, 600), "setup": (5, 600)}


def rate_limited(ip, kind):
    n, win = LIMITS[kind]
    now = time.time()
    with _lock:
        q = [t for t in _hits.get((ip, kind), []) if now - t < win]
        q.append(now); _hits[(ip, kind)] = q
    return len(q) > n


def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "business"


def new_slug(name):
    base = slugify(name)
    while True:
        s = f"{base}-{secrets.token_hex(2)}"
        if not store.slug_exists(s):
            return s


def abs_url(handler, path):
    base = pages.base_url()
    if not base:
        proto = handler.headers.get("X-Forwarded-Proto") or "http"
        base = f"{proto}://{handler.headers.get('Host', 'localhost')}"
    return base + path


def onboard(url, owner_email="", name_override="", slug=None, admin_key=None):
    """Scrape + create an assistant. Always creates one (empty data if the scrape fails) so the owner can fill the form."""
    t0 = time.time()
    try:
        url = scraper.normalize_url(url)
    except ValueError as ex:
        return None, str(ex)
    r = scraper.scrape(url)
    data = r["data"]
    if not r["ok"]:
        host = urllib.parse.urlparse(url).hostname or "business"
        data = {"name": re.sub(r"[-_]", " ", host.removeprefix("www.").split(".")[0]).title(), "website": url, "phones": [],
                "emails": [], "address": "", "hours": [], "services": [], "prices": [], "faqs": [], "chunks": [], "description": ""}
    if name_override:
        data["name"] = name_override
    slug = slug or new_slug(data["name"])
    key = store.create_business(slug, data.get("website", url), data, owner_email, r["quality"], r["notes"], admin_key)
    return {"slug": slug, "key": key, "name": data["name"], "quality": r["quality"], "notes": r["notes"], "scrape_ok": r["ok"],
            "pages": r.get("pages", []), "seconds": round(time.time() - t0, 1), "data": data}, None


def bot_public(b):
    d = b["data"]
    qr = []
    if d.get("hours"):
        qr.append("Opening hours?")
    if d.get("services"):
        qr.append("What services do you offer?")
    if d.get("prices"):
        qr.append("Prices?")
    return {"slug": b["slug"], "name": d.get("name", b["slug"]), "color": d.get("color") or "#4f46e5",
            "greeting": d.get("greeting") or f"Hi! I'm the assistant for {d.get('name', 'this business')}. Ask me anything, or request a booking, even after hours.",
            "services": d.get("services", [])[:15], "quick_replies": qr[:3]}


def save_booking(b, d):
    if d.get("website_url"):  # honeypot
        return True, "Thanks! Your request has been sent."
    rec = {k: re.sub(r"\s+", " ", str(d.get(k, ""))).strip()[:300] for k in ("name", "phone", "service", "preferred_time", "note", "page")}
    if len(rec["name"]) < 2:
        return False, "Please add your name."
    if len(re.sub(r"\D", "", rec["phone"])) < 7:
        return False, "Please add a phone number we can call."
    bid = store.add_booking(b["slug"], rec)
    name = b["data"].get("name", b["slug"])
    body = (f"New booking request for {name} (via your website assistant)\n\n"
            f"Name: {rec['name']}\nPhone: {rec['phone']}\nService: {rec['service'] or '-'}\nPreferred time: {rec['preferred_time'] or '-'}\n"
            f"Customer asked: {rec['note'] or '-'}\nPage: {rec['page'] or '-'}\n\nPlease call the customer to confirm.\n"
            f"All requests: your BookBot dashboard link.\n")

    def go():
        st = notify.send_email(b.get("owner_email") or "", f"New booking request: {rec['name']} ({rec['service'] or 'service not specified'})", body)
        cc = os.getenv("NOTIFY_BCC")
        if cc:
            notify.send_email(cc, f"[BookBot copy] {name}: booking request", body)
        store.set_booking_notified(bid, st if b.get("owner_email") else "logged (no owner email set)")
    threading.Thread(target=go, daemon=True).start()
    return True, f"Thanks {rec['name'].split()[0]}! Your request has been sent to {name}. They'll call you to confirm."


class H(BaseHTTPRequestHandler):
    server_version = "BookBot/1.0"

    def log_message(self, fmt, *args):
        if os.getenv("ACCESS_LOG"):
            super().log_message(fmt, *args)

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    def cors(self):
        return {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}

    def json(self, code, obj, cors=False):
        self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", self.cors() if cors else None)

    def body(self):
        n = min(int(self.headers.get("Content-Length") or 0), 64000)
        raw = self.rfile.read(n) if n else b""
        if "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
        return json.loads(raw or b"{}")

    def do_OPTIONS(self):
        self.send(204, b"", "text/plain", self.cors())

    def do_HEAD(self):
        self.do_GET()

    def static(self, name):
        path = os.path.join(ROOT, "public", os.path.basename(name))
        if not os.path.isfile(path):
            return self.send(404, pages.not_found())
        ctype = {"js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
        self.send(200, open(path, "rb").read(), ctype, {"Cache-Control": "public, max-age=300", **self.cors()})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p, q = u.path, urllib.parse.parse_qs(u.query)
        key = q.get("key", [""])[0]
        if p == "/":
            return self.send(200, pages.landing())
        if p == "/healthz":
            return self.json(200, {"ok": True, "llm": "openai" if os.getenv("OPENAI_API_KEY") else "rules", "smtp": bool(os.getenv("SMTP_HOST"))})
        if p == "/widget.js":
            return self.static("widget.js")
        if p.startswith("/static/"):
            return self.static(p[8:])
        m = re.fullmatch(r"/api/bot/([a-z0-9-]+)", p)
        if m:
            b = store.get_business(m.group(1))
            return self.json(200 if b else 404, bot_public(b) if b else {"error": "not found"}, cors=True)
        m = re.fullmatch(r"/demo/([a-z0-9-]+)/?", p)
        if m:
            b = store.get_business(m.group(1))
            return self.send(200, pages.demo(b)) if b else self.send(404, pages.not_found("This demo doesn't exist"))
        m = re.fullmatch(r"/(dashboard|edit)/([a-z0-9-]+)/?", p)
        if m:
            b = store.get_business(m.group(2))
            if not store.check_key(b, key):
                return self.send(403, pages.not_found("This link is not valid. Use the private link you got when you created the assistant."))
            if m.group(1) == "edit":
                return self.send(200, pages.edit(b, key, saved=q.get("saved") == ["1"]))
            return self.send(200, pages.dashboard(b, store.list_bookings(b["slug"]), key, abs_url(self, "")))
        if p == "/admin":
            tok = os.getenv("ADMIN_TOKEN")
            if not tok or not secrets.compare_digest(q.get("token", [""])[0], tok):
                return self.send(403, pages.not_found("Forbidden"))
            return self.send(200, pages.admin(*store.admin_overview(), tok))
        if p == "/robots.txt":
            return self.send(200, "User-agent: *\nDisallow: /demo/\nDisallow: /dashboard/\nDisallow: /edit/\nDisallow: /admin\n", "text/plain")
        self.send(404, pages.not_found())

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            d = self.body()
            if not isinstance(d, dict):
                raise ValueError
        except ValueError:
            return self.json(400, {"ok": False, "error": "bad request"}, cors=True)
        ip = self.ip()
        if p == "/api/chat":
            if rate_limited(ip, "chat"):
                return self.json(429, {"error": "Too many messages, please wait a minute."}, cors=True)
            b = store.get_business(str(d.get("bot", "")))
            if not b:
                return self.json(404, {"error": "assistant not found"}, cors=True)
            hist = d.get("history") if isinstance(d.get("history"), list) else []
            r = kb.answer(b["data"], str(d.get("message", "")), hist)
            return self.json(200, r, cors=True)
        if p == "/api/booking":
            if rate_limited(ip, "booking"):
                return self.json(429, {"ok": False, "error": "Too many requests, please try later."}, cors=True)
            b = store.get_business(str(d.get("bot", "")))
            if not b:
                return self.json(404, {"ok": False, "error": "assistant not found"}, cors=True)
            ok, msg = save_booking(b, d)
            return self.json(200 if ok else 400, {"ok": ok, "message": msg, "error": None if ok else msg}, cors=True)
        if p == "/api/onboard":
            if rate_limited(ip, "onboard"):
                return self.json(429, {"ok": False, "error": "Too many demos from your network. Please try again later."})
            owner = str(d.get("owner_email", "")).strip()[:160]
            if owner and not EMAIL_RE.match(owner):
                owner = ""
            res, err = onboard(str(d.get("url", ""))[:500], owner)
            if err:
                return self.json(400, {"ok": False, "error": err})
            demo, dash = abs_url(self, f"/demo/{res['slug']}"), abs_url(self, f"/dashboard/{res['slug']}?key={res['key']}")
            if owner:
                threading.Thread(target=notify.send_email, args=(owner, f"Your BookBot assistant for {res['name']}",
                                 f"Your assistant is ready.\n\nPublic demo: {demo}\nPrivate dashboard (keep it secret): {dash}\n"), daemon=True).start()
            return self.json(200, {"ok": True, "slug": res["slug"], "name": res["name"], "quality": res["quality"], "notes": res["notes"],
                                   "seconds": res["seconds"], "demo_url": demo, "dashboard_url": dash,
                                   "edit_url": abs_url(self, f"/edit/{res['slug']}?key={res['key']}")})
        if p == "/api/setup-request":
            if rate_limited(ip, "setup"):
                return self.json(429, {"ok": False, "error": "Too many requests, please try later."})
            if d.get("company_site"):
                return self.json(200, {"ok": True, "message": "Thanks! We'll be in touch within one business day."})
            rec = {k: str(d.get(k, "")).strip()[:2000] for k in ("name", "email", "website", "plan", "message")}
            if not rec["name"] or not EMAIL_RE.match(rec["email"]):
                return self.json(400, {"ok": False, "error": "Please add your name and a valid email."})
            rid = store.add_setup_request(rec)
            body = "New BookBot setup request\n\n" + "\n".join(f"{k.title()}: {v or '-'}" for k, v in rec.items())

            def go():
                store.set_setup_notified(rid, notify.send_email(SETUP_TO, f"BookBot setup request: {rec['name']} ({rec['plan']})", body, reply_to=rec["email"]))
            threading.Thread(target=go, daemon=True).start()
            return self.json(200, {"ok": True, "message": "Thanks! We'll be in touch within one business day."})
        m = re.fullmatch(r"/edit/([a-z0-9-]+)/?", p)
        if m:
            b = store.get_business(m.group(1))
            key = q.get("key", [""])[0]
            if not store.check_key(b, key):
                return self.send(403, pages.not_found("This link is not valid."))
            data = dict(b["data"])
            lines = lambda k: [x.strip() for x in str(d.get(k, "")).splitlines() if x.strip()][:40]
            csv_ = lambda k: [x.strip() for x in str(d.get(k, "")).split(",") if x.strip()][:4]
            data.update({"name": str(d.get("name", "")).strip()[:120] or data.get("name", b["slug"]), "phones": csv_("phones"), "emails": csv_("emails"),
                         "address": str(d.get("address", "")).strip()[:300], "hours": lines("hours"), "services": lines("services"), "prices": lines("prices")})
            faqs = []
            for block in re.split(r"\n\s*\n", str(d.get("faqs", "")).replace("\r", "")):
                mm = re.match(r"\s*Q:\s*(.+?)\s*\n\s*A:\s*(.+)", block, re.S)
                if mm:
                    faqs.append({"q": mm.group(1).strip()[:300], "a": re.sub(r"\s+", " ", mm.group(2)).strip()[:1000]})
            data["faqs"] = faqs[:40]
            owner = str(d.get("owner_email", "")).strip()
            store.update_business(b["slug"], data, owner if EMAIL_RE.match(owner) else "")
            self.send_response(303); self.send_header("Location", f"/edit/{b['slug']}?key={urllib.parse.quote(key)}&saved=1"); self.end_headers()
            return
        self.json(404, {"error": "not found"})


def main():
    store.init()
    port = int(os.getenv("PORT", "8090"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print(f"BookBot on http://localhost:{port}  llm={'openai' if os.getenv('OPENAI_API_KEY') else 'rules'}  smtp={'on' if os.getenv('SMTP_HOST') else 'off (emails logged to data/outbox.jsonl)'}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
