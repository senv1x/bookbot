"""End-to-end test: fixture website -> onboarding -> widget chat -> booking -> dashboard -> email (SMTP sink) ->
setup request -> manual edit after a failed scrape. Run: python3 tests/test_e2e.py [--real https://some-site]"""
import json, os, subprocess, sys, tempfile, time, http.server, threading, functools, socket
import requests

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def wait(url, t=10):
    for _ in range(int(t * 10)):
        try:
            requests.get(url, timeout=1); return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("not up: " + url)


def main():
    real = sys.argv[sys.argv.index("--real") + 1] if "--real" in sys.argv else None
    tmp = tempfile.mkdtemp(prefix="bookbot-test-")
    site_port, smtp_port, app_port = free_port(), free_port(), free_port()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=os.path.join(HERE, "fixture_site"))
    site = http.server.ThreadingHTTPServer(("127.0.0.1", site_port), handler)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    mails = os.path.join(tmp, "mails.txt")
    smtp = subprocess.Popen([sys.executable, os.path.join(HERE, "smtp_sink.py"), str(smtp_port), mails])
    env = {**os.environ, "PORT": str(app_port), "DATA_DIR": tmp, "DATABASE_PATH": os.path.join(tmp, "t.db"), "ALLOW_PRIVATE_SCRAPE": "1",
           "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(smtp_port), "SMTP_SECURITY": "none", "SMTP_FROM": "bookbot@test.local",
           "ADMIN_TOKEN": "t0k", "OPENAI_API_KEY": "", "SETUP_REQUEST_TO": "shipfastlabs.dev@gmail.com"}
    env.pop("EMAIL_DRY_RUN", None)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env)
    B = f"http://127.0.0.1:{app_port}"
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))

    try:
        wait(B + "/healthz")
        html = requests.get(B + "/").text
        check("landing headline", "Never lose a booking" in html and "$29" in html and "$59" in html and "$299" in html)
        t0 = time.time()
        r = requests.post(B + "/api/onboard", json={"url": f"http://127.0.0.1:{site_port}/", "owner_email": "owner@sunnysmile.test"}).json()
        check("onboard ok", r.get("ok"), r)
        check("onboard under 30s", time.time() - t0 < 30)
        slug, dash = r["slug"], r["dashboard_url"]
        check("business name scraped", r["name"] == "Sunny Smile Dental", r["name"])
        check("scrape quality good", r["quality"] == "good", r)
        demo = requests.get(B + f"/demo/{slug}").text
        check("demo page renders", "Sunny Smile Dental" in demo and 'data-bot="' + slug in demo)
        check("demo hides dashboard key", r["dashboard_url"].split("key=")[1] not in demo)
        check("widget.js served", "BookBot" in requests.get(B + "/widget.js").text)
        cfg = requests.get(B + f"/api/bot/{slug}").json()
        check("bot config has services", len(cfg["services"]) >= 3, cfg["services"])

        def ask(q):
            return requests.post(B + "/api/chat", json={"bot": slug, "message": q}).json()
        a = ask("What are your opening hours?"); check("hours answer", "09:00" in a["answer"] or "9:00" in a["answer"], a)
        a = ask("How much is teeth whitening?"); check("price answer", "295" in a["answer"], a)
        a = ask("Do you have parking?"); check("faq answer", "free parking" in a["answer"].lower(), a)
        a = ask("What's your phone number?"); check("phone answer", "7946" in a["answer"], a)
        a = ask("Where are you?"); check("address answer", "High Street" in a["answer"], a)
        a = ask("Do you do implants?"); check("service answer", "implant" in a["answer"].lower(), a)
        a = ask("I want to book a check-up"); check("booking intent", a["booking"] is True, a)
        a = ask("Do you sell bicycles?"); check("unknown -> handoff + booking form", a["booking"] and a["source"] == "handoff", a)
        b = requests.post(B + "/api/booking", json={"bot": slug, "name": "Anna Test", "phone": "07700 900456", "service": "Check-ups",
                                                     "preferred_time": "Tuesday 10am", "note": "first visit"}).json()
        check("booking saved", b.get("ok"), b)
        bad = requests.post(B + "/api/booking", json={"bot": slug, "name": "X", "phone": "12"})
        check("booking validation", bad.status_code == 400)
        time.sleep(1.5)
        dh = requests.get(dash).text
        check("dashboard lists booking", "Anna Test" in dh and "Tuesday 10am" in dh)
        check("dashboard shows email sent", ">sent<" in dh)
        check("dashboard rejects bad key", requests.get(B + f"/dashboard/{slug}?key=nope").status_code == 403)
        m = open(mails).read() if os.path.exists(mails) else ""
        check("owner email delivered via SMTP", "To: owner@sunnysmile.test" in m and "Anna Test" in m, m[:300])
        s = requests.post(B + "/api/setup-request", json={"name": "Bob Owner", "email": "bob@shop.test", "website": "shop.test", "plan": "pro", "message": "hi"}).json()
        check("setup request accepted", s.get("ok"), s)
        time.sleep(1.5)
        m = open(mails).read() if os.path.exists(mails) else ""
        check("setup request emailed to shipfastlabs", "To: shipfastlabs.dev@gmail.com" in m and "Bob Owner" in m)
        check("admin page", "Bob Owner" in requests.get(B + "/admin?token=t0k").text and requests.get(B + "/admin?token=x").status_code == 403)
        f = requests.post(B + "/api/onboard", json={"url": "http://127.0.0.1:1/"}).json()
        check("failed scrape still creates assistant", f.get("ok") and f["quality"] == "failed", f)
        key = f["edit_url"].split("key=")[1]
        e = requests.post(B + f"/edit/{f['slug']}?key={key}", data={"name": "Fixed Garage", "owner_email": "", "phones": "0161 000 0000",
                          "hours": "Mon-Fri 8am-6pm", "services": "MOT\nServicing", "faqs": "Q: Do you do MOTs?\nA: Yes, Class 4 MOTs daily."})
        check("manual edit saves", e.status_code == 200 and "Saved" in e.text)
        a = requests.post(B + "/api/chat", json={"bot": f["slug"], "message": "Do you do MOTs?"}).json()
        check("edited data used in answers", "Class 4" in a["answer"], a)
        sys.path.insert(0, ROOT); os.environ.pop("ALLOW_PRIVATE_SCRAPE", None); os.environ.pop("SCRAPE_ALLOW_NETS", None)
        import scraper
        try:
            scraper._host_ok("127.0.0.1"); blocked = False
        except scraper.ScrapeBlocked:
            blocked = True
        check("ssrf guard rejects private IP by default", blocked)
        if real:
            t0 = time.time(); r = requests.post(B + "/api/onboard", json={"url": real}).json()
            print("REAL", real, round(time.time() - t0, 1), "s", r.get("quality"), r.get("name"), r.get("notes"))
            for q in ("What are your opening hours?", "What services do you offer?", "How can I contact you?"):
                print("  Q:", q, "->", requests.post(B + "/api/chat", json={"bot": r["slug"], "message": q}).json()["answer"][:200])
    finally:
        app.terminate(); smtp.terminate(); site.shutdown()
    print("ALL PASSED" if ok else "SOME TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
