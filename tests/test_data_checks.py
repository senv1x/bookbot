"""Offline checks: the demo-data audit catches bad hours, all seeds pass it, and price matching prefers base services."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts")]
import kb
from verify_demos import audit, audit_seeds

bad = {"hours": ["Tuesday 9am-5pm", "Monday 9am-5pm", "Monday 2pm-6pm", "Sun: 12:00 AM – 4:00 PM", "Fri 25:00 - 18:00.."]}
issues = " | ".join(audit(bad, [("q", None, "Call us.. today")]))
for want in ("duplicate weekdays: mon", "Mon->Sun order", "suspicious midnight", "impossible time", "double punctuation in hours", "double punctuation in answer"):
    assert want in issues, (want, issues)
print("PASS audit flags bad hours")
assert audit({"hours": ["Monday – Friday: 9am – 5pm", "Saturday: Closed", "Sunday: Closed"]}, [("q", None, "Wait... ok.")]) == []
print("PASS audit accepts clean hours")
assert audit_seeds() == 0
print("PASS all seeds pass the audit")

d = {"name": "Dog Groomers", "website": "https://example.com/x", "services": ["Dog grooming"], "phones": ["01234 567890"],
     "prices": ["Full Groom – Toy: £39", "Full Groom – Large: £61", "Shaving – £10 added to full groom", "Nail Clipping – £12"]}
a = kb.rule_answer(d, "How much is a full groom?")["answer"]
assert "£39" in a and "£61" in a and "£10" not in a and "dog's size" in a, a
a = kb.rule_answer(d, "How much is teeth cleaning?")["answer"]
assert "don't have a listed price" in a and "£" not in a, a
a = kb.rule_answer(d, "How much is nail clipping?")["answer"]
assert "£12" in a and "£39" not in a, a
assert kb.tidy("Mon–Fri 9am – 5pm.. Call ££65") == "Mon–Fri 9am – 5pm. Call £65"
print("PASS price matching prefers base services; tidy")
print("ALL PASSED")
