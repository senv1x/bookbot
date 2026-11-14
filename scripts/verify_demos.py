"""Check every seeded demo on a running server: page loads and the assistant answers real questions.

  python3 scripts/verify_demos.py --server http://localhost:8090 --base https://PUBLIC --sales sales.csv --out demo-links.csv"""
import argparse, csv, glob, html, json, os, re, sys
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from server import slugify  # noqa: E402

QS = ["What are your opening hours?", "What services do you offer?", "How much does it cost?", "How can I contact you?"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8090"); ap.add_argument("--base", default=None)
    ap.add_argument("--sales", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base = (a.base or a.server).rstrip("/")
    rows = list(csv.DictReader(open(a.sales, encoding="utf-8")))
    out = []
    for row in rows:
        slug = slugify(row["business"])
        seed = json.load(open(os.path.join(ROOT, "seed", "demos", slug + ".json"), encoding="utf-8"))
        d = seed["data"]
        page = requests.get(f"{a.server}/demo/{slug}", timeout=20)
        loads = page.status_code == 200 and html.escape(d["name"]) in page.text
        answers = []
        for q in QS:
            r = requests.post(f"{a.server}/api/chat", json={"bot": slug, "message": q}, timeout=30).json()
            answers.append((q, r.get("source"), r.get("answer", "")))
        good = [x for x in answers if x[1] not in ("handoff", "hours-none", "prices-none", None)]
        b = requests.post(f"{a.server}/api/chat", json={"bot": slug, "message": "I'd like to book an appointment"}, timeout=30).json()
        notes = [seed["notes"]]
        days = [m.lower()[:3] for h in d.get("hours", []) for m in re.findall(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b", h, re.I)]
        if len(days) != len(set(days)):
            notes.append("hours from several locations/pages are mixed, review before sending")
        if not d.get("hours"):
            notes.append("no opening hours found")
        if len(d.get("services", [])) < 3:
            notes.append("few services detected")
        out.append({
            "business": row["business"], "website": row["site"], "demo_url": f"{base}/demo/{slug}", "demo_path": f"/demo/{slug}",
            "scrape_quality": seed["quality"], "scrape_notes": "; ".join(n for n in notes if n),
            "page_loads": "yes" if loads else "NO", "questions_answered": f"{len(good)}/{len(QS)}",
            "booking_form_offered": "yes" if b.get("booking") else "NO",
            "sample_q": good[0][0] if good else "", "sample_answer": (good[0][2][:220] if good else answers[0][2][:220]),
            "services_detected": "; ".join(d.get("services", [])[:8]), "hours_detected": "; ".join(d.get("hours", [])[:7]),
            "outreach_status": row.get("status", ""),
        })
        print(f"{'OK ' if loads and good else 'BAD'} {len(good)}/{len(QS)} {seed['quality']:8} {row['business']}")
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
