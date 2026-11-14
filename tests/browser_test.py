"""Real-browser test (optional): landing onboarding with a real website -> demo page -> widget chat -> booking form ->
dashboard shows the request; plus the widget embedded on a different-origin page. Needs playwright + Chrome.
  python tests/browser_test.py http://localhost:8090 https://some-business-site.com [out_dir]"""
import os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from playwright.sync_api import sync_playwright

B, SITE = sys.argv[1].rstrip("/"), sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else "/tmp/bookbot-shots"
os.makedirs(OUT, exist_ok=True)
CHROME = os.getenv("CHROME_PATH", "/usr/bin/google-chrome")


def run():
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 1280, "height": 900})
        pg.goto(B + "/"); pg.screenshot(path=f"{OUT}/01-landing.png", full_page=True)
        pg.fill("#url", SITE); t0 = time.time(); pg.click("#go")
        pg.wait_for_selector("#res a.btn", timeout=60000)
        print(f"onboarding via UI took {time.time() - t0:.1f}s")
        pg.screenshot(path=f"{OUT}/02-onboarded.png")
        demo = pg.get_attribute("#res a.btn", "href")
        dash = pg.locator("#res a").nth(3).get_attribute("href")
        pg.goto(demo)
        w = pg.locator("#bookbot-widget")
        w.locator(".panel.open").wait_for(timeout=15000)
        w.locator("form.in input").fill("What are your opening hours?"); w.locator("form.in button").click()
        pg.wait_for_function("() => { const r = document.querySelector('#bookbot-widget').shadowRoot; const m = r.querySelectorAll('.m.bot'); return m.length >= 2 && !m[m.length-1].classList.contains('typing') }", timeout=30000)
        print("bot:", w.locator(".m.bot").last.inner_text()[:200])
        w.locator("form.in input").fill("I'd like to book an appointment"); w.locator("form.in button").click()
        w.locator("form.bk").wait_for(timeout=30000)
        w.locator("form.bk input[name=name]").fill("Browser Test")
        w.locator("form.bk input[name=phone]").fill("07700 900999")
        w.locator("form.bk input[name=preferred_time]").fill("Friday afternoon")
        pg.screenshot(path=f"{OUT}/03-demo-booking-form.png")
        w.locator("form.bk button").click()
        pg.wait_for_function("() => document.querySelector('#bookbot-widget').shadowRoot.textContent.includes('Your request has been sent')", timeout=20000)
        pg.screenshot(path=f"{OUT}/04-booking-sent.png")
        time.sleep(1)
        pg.goto(dash); assert "Browser Test" in pg.content(), "booking missing on dashboard"
        pg.screenshot(path=f"{OUT}/05-dashboard.png", full_page=True)
        print("dashboard shows booking: yes")
        slug = demo.rstrip("/").split("/")[-1]
        page_html = f'<!doctype html><html><body style="font-family:sans-serif;padding:40px"><h1>Client website (different origin)</h1><script src="{B}/widget.js" data-bot="{slug}" defer></script></body></html>'.encode()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(page_html)
        srv = ThreadingHTTPServer(("127.0.0.1", 18777), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        pg.goto("http://127.0.0.1:18777/")
        w = pg.locator("#bookbot-widget"); w.locator(".fab").click()
        w.locator("form.in input").fill("What services do you offer?"); w.locator("form.in button").click()
        pg.wait_for_function("() => { const m = document.querySelector('#bookbot-widget').shadowRoot.querySelectorAll('.m.bot'); return m.length >= 2 && !m[m.length-1].classList.contains('typing') }", timeout=30000)
        print("cross-origin embed bot:", w.locator(".m.bot").last.inner_text()[:200])
        pg.screenshot(path=f"{OUT}/06-embedded-other-origin.png")
        mob = br.new_page(viewport={"width": 390, "height": 844}); mob.goto(B + "/"); mob.screenshot(path=f"{OUT}/07-landing-mobile.png", full_page=True)
        br.close()
        print("BROWSER TEST PASSED, screenshots in", OUT)


run()
