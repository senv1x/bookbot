"""Generate seeded demo assistants for a list of businesses (CSV with columns business, site).

  python3 scripts/make_demos.py sales.csv --out demo-links.csv --base https://bookbot.example.com

Writes seed/demos/<slug>.json (loaded at server start, so demos survive restarts / redeploys on ephemeral disks)
and a CSV with the demo URL and scrape-quality notes per business. Never contacts the businesses."""
import argparse, csv, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scraper  # noqa: E402
from server import slugify  # noqa: E402


OV_PATH = os.path.join(ROOT, "seed", "overrides.json")
OVERRIDES = json.load(open(OV_PATH, encoding="utf-8")) if os.path.exists(OV_PATH) else {}


def build(row):
    name, site = row["business"].strip(), row["site"].strip()
    t0 = time.time()
    r = scraper.scrape(site, budget=60, workers=2, page_timeout=15)
    for _ in range(2):  # small-business hosts are flaky: retry weak results
        if r["quality"] in ("good", "partial"):
            break
        time.sleep(3)
        r2 = scraper.scrape(site, budget=60, workers=2, page_timeout=15)
        if ["failed", "poor", "partial", "good"].index(r2["quality"]) > ["failed", "poor", "partial", "good"].index(r["quality"]):
            r = r2
    data = r["data"]
    if not r["ok"]:
        data = {"website": site, "phones": [], "emails": [], "address": "", "hours": [], "services": [], "prices": [], "faqs": [],
                "chunks": [], "description": ""}
    data["name"] = name  # the list's name is more reliable than page titles
    slug = slugify(name)
    old_path = os.path.join(ROOT, "seed", "demos", slug + ".json")
    if os.path.exists(old_path) and not os.environ.get("FRESH_SCRAPE"):
        # a page that timed out this run shouldn't wipe what an earlier run found
        old = json.load(open(old_path, encoding="utf-8"))["data"]
        for k in ("prices", "faqs", "chunks"):
            if len(old.get(k) or []) >= 3 and len(data.get(k) or []) < len(old[k]) / 2:
                data[k] = old[k]
    ov = OVERRIDES.get(slug, {})
    data.update({k: v for k, v in ov.items() if not k.startswith("_")})
    seed = {"slug": slug, "website": data.get("website", site), "quality": r["quality"], "notes": r["notes"] + ("; services curated by hand" if ov.get("services") else ""), "data": data,
            "generated_at": time.strftime("%Y-%m-%d %H:%M")}
    with open(os.path.join(ROOT, "seed", "demos", slug + ".json"), "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=1)
    return row, slug, r, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv"); ap.add_argument("--out", required=True); ap.add_argument("--base", default="http://localhost:8090")
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.csv, encoding="utf-8")) if not re.search(r"bounced|skipped", r.get("status", ""), re.I)]
    os.makedirs(os.path.join(ROOT, "seed", "demos"), exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(build, rows))
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["business", "website", "demo_url", "scrape_quality", "scrape_notes", "seconds"])
        for row, slug, r, secs in results:
            w.writerow([row["business"], row["site"], f"{a.base.rstrip('/')}/demo/{slug}", r["quality"], r["notes"], secs])
            print(f"{r['quality']:8} {secs:5}s {row['business']}")


if __name__ == "__main__":
    main()
