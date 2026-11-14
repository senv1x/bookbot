"""SQLite storage for BookBot (stdlib only). DB path: DATABASE_PATH env or data/bookbot.db."""
import json, os, secrets, sqlite3, threading, time, glob, hmac, hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.getenv("DATA_DIR") or os.path.join(ROOT, "data")
DB = os.getenv("DATABASE_PATH") or os.path.join(DATA, "bookbot.db")
_lock = threading.Lock()


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS businesses(
          slug TEXT PRIMARY KEY, name TEXT, website TEXT, data TEXT, owner_email TEXT DEFAULT '',
          admin_key TEXT, quality TEXT, notes TEXT, seeded INTEGER DEFAULT 0, created_at REAL);
        CREATE TABLE IF NOT EXISTS bookings(
          id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, name TEXT, phone TEXT, service TEXT,
          preferred_time TEXT, note TEXT, page TEXT, notified TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS setup_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, website TEXT, plan TEXT,
          message TEXT, notified TEXT, created_at REAL);
        """)
    load_seeds()


def seed_key(slug):
    """Dashboard key for seeded demos: HMAC(SEED_ADMIN_SECRET, slug). No secret -> no dashboard."""
    sec = os.getenv("SEED_ADMIN_SECRET")
    return hmac.new(sec.encode(), slug.encode(), hashlib.sha256).hexdigest()[:32] if sec else ""


def load_seeds():
    for path in sorted(glob.glob(os.path.join(ROOT, "seed", "demos", "*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        with _lock, _conn() as c:
            c.execute("INSERT OR REPLACE INTO businesses(slug,name,website,data,owner_email,admin_key,quality,notes,seeded,created_at)"
                      " VALUES(?,?,?,?,?,?,?,?,1,COALESCE((SELECT created_at FROM businesses WHERE slug=?),?))",
                      (d["slug"], d["data"].get("name", d["slug"]), d.get("website", ""), json.dumps(d["data"]), "",
                       seed_key(d["slug"]), d.get("quality", ""), d.get("notes", ""), d["slug"], time.time()))


def create_business(slug, website, data, owner_email="", quality="", notes="", admin_key=None):
    key = admin_key or secrets.token_urlsafe(18)
    with _lock, _conn() as c:
        c.execute("INSERT INTO businesses(slug,name,website,data,owner_email,admin_key,quality,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (slug, data.get("name", slug), website, json.dumps(data), owner_email, key, quality, notes, time.time()))
    return key


def slug_exists(slug):
    with _conn() as c:
        return c.execute("SELECT 1 FROM businesses WHERE slug=?", (slug,)).fetchone() is not None


def get_business(slug):
    with _conn() as c:
        r = c.execute("SELECT * FROM businesses WHERE slug=?", (slug,)).fetchone()
    if not r:
        return None
    b = dict(r); b["data"] = json.loads(b["data"] or "{}")
    return b


def update_business(slug, data, owner_email):
    with _lock, _conn() as c:
        c.execute("UPDATE businesses SET data=?, name=?, owner_email=?,"
                  " quality=CASE WHEN quality IN ('failed','poor') THEN 'edited' ELSE quality END WHERE slug=?",
                  (json.dumps(data), data.get("name", slug), owner_email, slug))


def check_key(b, key):
    return bool(b and b.get("admin_key") and key and hmac.compare_digest(b["admin_key"], key))


def add_booking(slug, rec):
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO bookings(slug,name,phone,service,preferred_time,note,page,notified,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (slug, rec["name"], rec["phone"], rec["service"], rec["preferred_time"], rec["note"], rec["page"], "", time.time()))
        return cur.lastrowid


def set_booking_notified(bid, status):
    with _lock, _conn() as c:
        c.execute("UPDATE bookings SET notified=? WHERE id=?", (status, bid))


def list_bookings(slug):
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM bookings WHERE slug=? ORDER BY id DESC LIMIT 500", (slug,))]


def add_setup_request(rec):
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO setup_requests(name,email,website,plan,message,notified,created_at) VALUES(?,?,?,?,?,?,?)",
                        (rec["name"], rec["email"], rec["website"], rec["plan"], rec["message"], "", time.time()))
        return cur.lastrowid


def set_setup_notified(rid, status):
    with _lock, _conn() as c:
        c.execute("UPDATE setup_requests SET notified=? WHERE id=?", (status, rid))


def admin_overview():
    with _conn() as c:
        bs = [dict(r) for r in c.execute("SELECT b.slug,b.name,b.website,b.quality,b.seeded,b.created_at,"
                                         "(SELECT COUNT(*) FROM bookings k WHERE k.slug=b.slug) AS n FROM businesses b ORDER BY created_at DESC")]
        sr = [dict(r) for r in c.execute("SELECT * FROM setup_requests ORDER BY id DESC LIMIT 200")]
    return bs, sr
