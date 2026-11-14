"""Checks the OpenAI code path against a local mock of /chat/completions (no real key needed), and the fallback on error."""
import json, os, sys, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
seen = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen["auth"], seen["system"] = self.headers.get("Authorization"), body["messages"][0]["content"]
        out = json.dumps({"choices": [{"message": {"content": "We're open Mon-Fri 9-5. Want me to request a booking? [BOOKING]"}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 18999), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="http://127.0.0.1:18999/v1")
import kb
d = {"name": "Test Dental", "hours": ["Mon-Fri 9-5"], "services": ["Check-ups"], "phones": ["0123 456 789"], "chunks": [{"text": "We love smiles and see new patients every week."}]}
r = kb.answer(d, "When are you open?")
ok = r["mode"] == "openai" and r["booking"] and "[BOOKING]" not in r["answer"] and seen["auth"] == "Bearer test-key" and "Mon-Fri 9-5" in seen["system"]
print("PASS openai path" if ok else f"FAIL openai path {r} {seen}")
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"
r2 = kb.answer(d, "When are you open?")
ok2 = r2["mode"] == "rules" and "Mon-Fri 9-5" in r2["answer"]
print("PASS fallback to rules when LLM fails" if ok2 else f"FAIL fallback {r2}")
sys.exit(0 if ok and ok2 else 1)
