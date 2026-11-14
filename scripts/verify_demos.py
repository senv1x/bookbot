"""Check every seeded demo on a running server: page loads and the assistant answers real questions.

  python3 scripts/verify_demos.py --server http://localhost:8090 --base https://PUBLIC --sales sales.csv --out demo-links.csv"""
import argparse, csv, glob, html, json, os, re, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server import slugify  # noqa: E402

def call(method, url, **kw):
    """HTTP with retries: free hosts cold-start and proxies drop TLS sessions now and then."""
    for attempt in range(5):
        try:
            r = requests.request(method, url, timeout=90, **kw)
            if r.status_code == 429:
                time.sleep(20); continue
            return r
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
DOUBLE_PUNCT = re.compile(r"(?<!\.)\.\s*\.(?!\.)|,\s*,|;\s*;|:\s*:|!\s*!|\?\s*\?|££|€€")


def audit(d, answers):
    """Data checks: duplicate weekdays, impossible times, Mon->Sun order, doubled punctuation."""
    issues, firsts = [], []
    for h in d.get("hours", []):
        m = DAY_RE.search(h)
        if m:
            firsts.append(DAYS.index(m.group(1).lower()[:3]))
        for hh, mm, ap in re.findall(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?", h, re.I):
            if int(mm) > 59 or int(hh) > 23 or (ap and int(hh) > 12):
                issues.append(f"impossible time in '{h}'")
        if re.search(r"\b12[:.]00\s*am\b", h, re.I):
            issues.append(f"suspicious midnight time in '{h}'")
        if DOUBLE_PUNCT.search(h):
            issues.append(f"double punctuation in hours '{h}'")
    seen = [DAYS[i] for i in firsts]
    dup = sorted({x for x in seen if seen.count(x) > 1})
    if dup:
        issues.append("duplicate weekdays: " + ",".join(dup))
    if firsts != sorted(firsts):
        issues.append("hours not in Mon->Sun order")
    for q, src, a in answers:
        if DOUBLE_PUNCT.search(a or ""):
            issues.append(f"double punctuation in answer to '{q}'")
    return issues


QS = ["What are your opening hours?", "What services do you offer?", "How much does it cost?", "How can I contact you?", "Are you open on Saturday?"]


def audit_seeds():
    """Offline check of every seed file (no server needed). Exit code 1 if anything fails."""
    bad = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "seed", "demos", "*.json"))):
        d = json.load(open(p, encoding="utf-8"))["data"]
        issues = audit(d, [("faq " + f.get("q", "")[:30], None, f.get("a", "")) for f in d.get("faqs", [])] + [("hours_note", None, d.get("hours_note", ""))])
        bad += bool(issues)
        print(("OK  " if not issues else "BAD ") + os.path.basename(p) + ("  !! " + " | ".join(issues) if issues else ""))
    return bad


def main():
    if "--audit-only" in sys.argv:
        sys.exit(1 if audit_seeds() else 0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8090"); ap.add_argument("--base", default=None)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between chat calls (live server rate limit: 40/min/IP)")
    ap.add_argument("--sales", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base = (a.base or a.server).rstrip("/")
    rows = [r for r in csv.DictReader(open(a.sales, encoding="utf-8")) if not re.search(r"bounced|skipped", r.get("status", ""), re.I)]
    out = []
    for row in rows:
        slug = slugify(row["business"])
        seed = json.load(open(os.path.join(ROOT, "seed", "demos", slug + ".json"), encoding="utf-8"))
        d = seed["data"]
        page = call("GET", f"{a.server}/demo/{slug}")
        loads = page.status_code == 200 and html.escape(d["name"]) in page.text
        answers = []
        for q in QS:
            time.sleep(a.delay)
            r = call("POST", f"{a.server}/api/chat", json={"bot": slug, "message": q}).json()
            answers.append((q, r.get("source"), r.get("answer", "")))
        # audit the hours the server actually serves (parsed from its hours answer), plus every answer's punctuation
        served = next((x[2] for x in answers if x[1] == "hours"), "")
        m = re.search(r"opening hours: (.*?)\. Outside these hours", served)
        issues = audit({"hours": m.group(1).split("; ") if m else d.get("hours", [])}, answers)
        good = [x for x in answers if x[1] not in ("handoff", "hours-none", "prices-none", None)]
        time.sleep(a.delay)
        b = call("POST", f"{a.server}/api/chat", json={"bot": slug, "message": "I'd like to book an appointment"}).json()
        notes = [seed["notes"]]
        days = [m.lower()[:3] for h in d.get("hours", []) for m in re.findall(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b", h, re.I)]
        if len(days) != len(set(days)):
            notes.append("hours from several locations/pages are mixed, review before sending")
        if not d.get("hours"):
            notes.append("no opening hours on the website; assistant says to contact them" if d.get("hours_note") else "no opening hours found")
        if len(d.get("services", [])) < 3:
            notes.append("few services detected")
        out.append({
            "business": row["business"], "website": row["site"], "demo_url": f"{base}/demo/{slug}", "demo_path": f"/demo/{slug}",
            "scrape_quality": seed["quality"], "scrape_notes": "; ".join(n for n in notes if n),
            "page_loads": "yes" if loads else "NO", "questions_answered": f"{len(good)}/{len(QS)}",
            "booking_form_offered": "yes" if b.get("booking") else "NO",
            "sample_q": good[0][0] if good else "", "sample_answer": (good[0][2][:220] if good else answers[0][2][:220]),
            "services_detected": "; ".join(d.get("services", [])[:8]), "hours_detected": "; ".join(d.get("hours", [])[:7]) or d.get("hours_note", ""),
            "data_checks": "ok" if not issues else " | ".join(issues),
            "outreach_status": row.get("status", ""),
        })
        print(f"{'OK ' if loads and good and not issues else 'BAD'} {len(good)}/{len(QS)} {seed['quality']:8} {row['business']}" + (f"  !! {issues}" if issues else ""))
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
