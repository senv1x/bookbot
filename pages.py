"""Server-rendered HTML pages (no template engine; everything escaped with html.escape)."""
import datetime as dt, json, os
from html import escape as e

PLANS = [
    ("starter", "Starter", "$29", "/mo", ["AI assistant trained on your website", "Booking requests 24/7", "Email alert for every request",
                                          "Dashboard with all requests", "One-line website embed"], "STRIPE_LINK_STARTER"),
    ("pro", "Pro", "$59", "/mo", ["Everything in Starter", "Edit answers, services and hours anytime", "Priority support",
                                  "Custom colours and greeting", "Up to 3 locations / sites"], "STRIPE_LINK_PRO"),
    ("setup", "Done-for-you setup", "$299", " one-off", ["We set it up and tune the answers", "Install on your website for you",
                                                       "Test bookings end to end", "Ready in 3 business days"], "STRIPE_LINK_SETUP"),
]


def base_url():
    return (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")


def layout(title, body, desc="BookBot answers questions and captures booking requests on your website, 24/7.", extra_head=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>💬</text></svg>">{extra_head}</head>
<body>{body}</body></html>"""


def nav():
    return """<div class="wrap"><nav class="top"><a class="logo" href="/">Book<span>Bot</span></a>
<div class="links"><a href="/#how">How it works</a><a href="/#pricing">Pricing</a><a href="/#setup">Request setup</a>
<a class="btn" href="/#try" style="color:#fff">Try it free</a></div></nav></div>"""


def foot():
    return f"""<footer><div class="wrap">BookBot by Shipfast Labs · <a href="mailto:shipfastlabs.dev@gmail.com">shipfastlabs.dev@gmail.com</a> · © {dt.date.today().year}</div></footer>"""


def landing():
    cards = ""
    for key, name, price, per, feats, env in PLANS:
        link = os.getenv(env, "").strip()
        cls = "btn" + ("" if key == "pro" else " ghost")
        label = "Book setup" if key == "setup" else "Get started"
        btn = (f'<a href="{e(link)}" target="_blank" rel="noopener" class="{cls}">{label}</a>' if link else
               f'<a href="#setup" class="{cls} plan-btn" data-plan="{key}">{label}</a>')
        cards += f"""<div class="card{' hl' if key == 'pro' else ''}">{'<span class="pill">Most popular</span>' if key == 'pro' else ''}
<h3>{name}</h3><div class="price">{price}<small>{per}</small></div><ul>{''.join(f'<li>{e(f)}</li>' for f in feats)}</ul>{btn}</div>"""
    body = nav() + f"""
<header class="hero wrap" id="try"><span class="pill">AI front desk for dentists, garages, salons, driving schools</span>
<h1>Never lose a booking<br>after hours</h1>
<p class="sub">BookBot reads your website, answers customer questions about services, prices and opening hours, and takes booking requests while you're closed. You get an email for every request.</p>
<form class="onb" id="onb"><input id="url" name="url" placeholder="yourbusiness.com" required autocomplete="url">
<button class="btn" id="go">Build my free demo</button></form>
<p class="small" style="margin-top:10px">Free demo in about 30 seconds. No card, no signup.</p>
<div class="result" id="res"></div></header>
<section class="alt" id="how"><div class="wrap"><h2>How it works</h2><p class="muted">From your website to a working assistant, without a setup call.</p>
<div class="grid3 steps"><div class="card"><h3>Enter your website</h3><p class="muted">BookBot reads your pages and pulls out services, prices, opening hours, FAQs and contact details.</p></div>
<div class="card"><h3>Try your assistant</h3><p class="muted">You get a demo link straight away. Ask it what your customers ask. Fix anything it got wrong in a simple form.</p></div>
<div class="card"><h3>Add one line to your site</h3><p class="muted">Paste one <code>&lt;script&gt;</code> tag. Booking requests land in your dashboard and your inbox.</p></div></div></div></section>
<section><div class="wrap"><h2>Built for small service businesses</h2>
<div class="grid3"><div class="card"><h3>Answers from your own site</h3><p class="muted">Replies only use what's on your website and what you add. If it doesn't know, it takes the customer's details instead of guessing.</p></div>
<div class="card"><h3>Captures the booking</h3><p class="muted">Name, phone, service and preferred time go straight to you, so you can confirm first thing in the morning.</p></div>
<div class="card"><h3>Works with what you have</h3><p class="muted">No new booking system needed. It works on WordPress, Wix, Squarespace or any site where you can paste a snippet.</p></div></div></div></section>
<section class="alt" id="pricing"><div class="wrap"><h2>Simple pricing</h2><p class="muted">Monthly plans, cancel anytime. Prices in USD.</p><div class="grid3">{cards}</div></div></section>
<section id="setup"><div class="wrap two"><div><h2>Request a setup</h2><p class="muted">Tell us about your business and we'll get back to you within one business day. We can set everything up for you.</p>
<p class="small">Questions? Email <a href="mailto:shipfastlabs.dev@gmail.com">shipfastlabs.dev@gmail.com</a>.</p></div>
<form class="card" id="setupf"><label>Your name</label><input name="name" required maxlength="120"><label>Email</label><input name="email" type="email" required maxlength="160">
<label>Website</label><input name="website" maxlength="300" placeholder="yourbusiness.com"><label>Plan</label>
<select name="plan"><option value="starter">Starter ($29/mo)</option><option value="pro">Pro ($59/mo)</option><option value="setup">Done-for-you setup ($299)</option><option value="unsure">Not sure yet</option></select>
<label>Anything we should know?</label><textarea name="message" maxlength="2000"></textarea>
<input name="company_site" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px">
<p><button class="btn">Send request</button></p><p class="small" id="setupmsg"></p></form></div></section>
{foot()}
<script src="/static/landing.js" defer></script>"""
    return layout("BookBot: never lose a booking after hours", body)


def _facts(d):
    rows = []
    if d.get("services"):
        rows.append(("Services", ", ".join(d["services"][:12])))
    if d.get("hours"):
        rows.append(("Opening hours", "; ".join(d["hours"][:8])))
    contact = ", ".join((d.get("phones") or [])[:2] + (d.get("emails") or [])[:1])
    if contact:
        rows.append(("Contact", contact))
    if d.get("address"):
        rows.append(("Address", d["address"]))
    if d.get("prices"):
        rows.append(("Prices found", f"{len(d['prices'])} price lines"))
    if d.get("faqs"):
        rows.append(("FAQs found", str(len(d["faqs"]))))
    return "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows) or "<dd class='muted'>Not much could be read from the website yet. Details can be added in the edit form.</dd>"


def demo(b):
    d = b["data"]
    name = d.get("name") or b["slug"]
    qs = ["What are your opening hours?", "What services do you offer?", "How much does it cost?", "I'd like to book an appointment"]
    chips = "".join(f'<button type="button" data-q="{e(q)}">{e(q)}</button>' for q in qs)
    body = f"""<div class="demo-bar"><div class="wrap">Live demo: an AI assistant for <b>{e(name)}</b>, generated by BookBot from public information on
<a href="{e(b['website'])}" target="_blank" rel="noopener nofollow">{e(b['website'])}</a>. Not yet installed on that website.</div></div>
{nav()}<div class="wrap two" style="padding:30px 20px 60px"><div><span class="pill">Demo</span>
<h1 style="font-size:38px;margin:10px 0">{e(name)}<br><span class="muted" style="font-size:24px">website assistant</span></h1>
<p class="muted">Try it in the chat window (bottom right). It answers from the business's website and takes booking requests after hours.</p>
<div class="chips">{chips}</div>
<h3 style="margin-top:28px">What the assistant learned from the website</h3><dl class="facts">{_facts(d)}</dl>
<p class="small">Something wrong or missing? The business owner can correct it in a simple form.</p></div>
<div><div class="card"><h3>Want this on your website?</h3><p class="muted">One line of code. Every booking request goes to your inbox.</p>
<p><a class="btn" href="/#pricing">See plans from $29/mo</a></p><p><a class="btn ghost" href="/#setup">Request done-for-you setup</a></p></div></div></div>
{foot()}
<script src="/widget.js" data-bot="{e(b['slug'])}" data-open="1" defer></script>
<script>document.querySelectorAll('.chips button').forEach(function(x){{x.onclick=function(){{window.BookBot&&window.BookBot.ask(x.dataset.q)}}}})</script>"""
    return layout(f"{name}: assistant demo (BookBot)", body, extra_head='<meta name="robots" content="noindex">')


def embed_snippet(slug, base=""):
    base = base_url() or base or "https://YOUR-BOOKBOT-DOMAIN"
    return f'<script src="{base}/widget.js" data-bot="{slug}" defer></script>'


def dashboard(b, bookings, key, base=""):
    d = b["data"]
    rows = "".join(f"""<tr><td>{dt.datetime.fromtimestamp(r['created_at']).strftime('%Y-%m-%d %H:%M')}</td><td>{e(r['name'])}</td>
<td><a href="tel:{e(r['phone'])}">{e(r['phone'])}</a></td><td>{e(r['service'])}</td><td>{e(r['preferred_time'])}</td><td>{e(r['note'])}</td>
<td class="small">{e(r['notified'] or '')}</td></tr>""" for r in bookings) or '<tr><td colspan="7" class="muted">No booking requests yet. Try the demo and send one.</td></tr>'
    owner = b.get("owner_email") or ""
    body = nav() + f"""<div class="wrap" style="padding:20px 20px 60px"><h1 style="margin:0">{e(d.get('name', b['slug']))} <span class="pill {e(b.get('quality') or '')}">{e(b.get('quality') or '')}</span></h1>
<p class="muted">Dashboard · keep this link private, it gives access to your requests.</p>
<p><a class="btn" href="/demo/{e(b['slug'])}" target="_blank">Open assistant</a> <a class="btn ghost" href="/edit/{e(b['slug'])}?key={e(key)}">Edit answers &amp; details</a></p>
{'' if owner else '<p class="notice">No notification email set. <a href="/edit/' + e(b['slug']) + '?key=' + e(key) + '">Add one</a> to get an email for every booking request.</p>'}
<h2 style="margin-top:30px">Booking requests ({len(bookings)})</h2><div style="overflow:auto"><table><tr><th>Received</th><th>Name</th><th>Phone</th><th>Service</th><th>Preferred time</th><th>Note</th><th>Email alert</th></tr>{rows}</table></div>
<h2 style="margin-top:36px">Add it to your website</h2><p class="muted">Paste this just before <code>&lt;/body&gt;</code> on every page (WordPress: a header/footer plugin; Wix: Settings, Custom code).</p>
<pre>{e(embed_snippet(b['slug'], base))}</pre><p class="small">Notifications go to: <b>{e(owner or 'not set')}</b> · Website: {e(b['website'])}</p></div>{foot()}"""
    return layout("Dashboard · BookBot", body, extra_head='<meta name="robots" content="noindex">')


def edit(b, key, saved=False):
    d = b["data"]
    faqs = "\n\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in d.get("faqs", []))

    def ta(name, label, val, hint=""):
        return f'<label>{label}</label><textarea name="{name}" rows="5">{e(val)}</textarea>' + (f'<div class="small">{hint}</div>' if hint else "")
    body = nav() + f"""<div class="wrap" style="padding:20px 20px 60px;max-width:820px"><h1>Edit your assistant</h1>
{'<p class="notice">Saved. The assistant uses the new details right away.</p>' if saved else ''}
{'<p class="notice">We could not read much from your website, so fill in the basics below. It takes about two minutes.</p>' if b.get('quality') in ('failed', 'poor') else ''}
<form method="post" action="/edit/{e(b['slug'])}?key={e(key)}" class="card">
<label>Business name</label><input name="name" value="{e(d.get('name', ''))}" required maxlength="120">
<label>Notification email (booking requests go here)</label><input name="owner_email" type="email" value="{e(b.get('owner_email') or '')}" maxlength="160">
<label>Phone(s)</label><input name="phones" value="{e(', '.join(d.get('phones', [])))}" maxlength="200">
<label>Public email</label><input name="emails" value="{e(', '.join(d.get('emails', [])))}" maxlength="200">
<label>Address</label><input name="address" value="{e(d.get('address', ''))}" maxlength="300">
{ta('hours', 'Opening hours (one per line)', chr(10).join(d.get('hours', [])), 'e.g. Mon-Fri: 9am-6pm')}
{ta('services', 'Services (one per line)', chr(10).join(d.get('services', [])))}
{ta('prices', 'Prices (one per line, optional)', chr(10).join(d.get('prices', [])))}
<label>FAQs</label><textarea name="faqs" rows="8" placeholder="Q: Do you take new patients?&#10;A: Yes, call or book here.">{e(faqs)}</textarea>
<div class="small">Write each question as "Q: ..." with the answer on the next line as "A: ...". Leave a blank line between them.</div>
<p style="margin-top:18px"><button class="btn">Save</button> <a href="/dashboard/{e(b['slug'])}?key={e(key)}">Back to dashboard</a></p></form></div>{foot()}"""
    return layout("Edit assistant · BookBot", body, extra_head='<meta name="robots" content="noindex">')


def admin(bs, srs, token):
    rows = "".join(f"<tr><td><a href='/demo/{e(x['slug'])}'>{e(x['slug'])}</a></td><td>{e(x['name'] or '')}</td><td class='small'>{e(x['website'] or '')}</td>"
                   f"<td><span class='pill {e(x['quality'] or '')}'>{e(x['quality'] or '')}</span></td><td>{'seed' if x['seeded'] else ''}</td><td>{x['n']}</td></tr>" for x in bs)
    srows = "".join(f"<tr><td>{dt.datetime.fromtimestamp(r['created_at']).strftime('%Y-%m-%d %H:%M')}</td><td>{e(r['name'])}</td><td>{e(r['email'])}</td>"
                    f"<td>{e(r['website'])}</td><td>{e(r['plan'])}</td><td>{e(r['message'])}</td><td class='small'>{e(r['notified'] or '')}</td></tr>" for r in srs)
    body = nav() + f"""<div class="wrap" style="padding:20px"><h1>Admin</h1><h2>Setup requests</h2><table><tr><th>When</th><th>Name</th><th>Email</th><th>Website</th><th>Plan</th><th>Message</th><th>Email</th></tr>{srows}</table>
<h2 style="margin-top:30px">Assistants ({len(bs)})</h2><table><tr><th>Slug</th><th>Name</th><th>Website</th><th>Scrape</th><th></th><th>Bookings</th></tr>{rows}</table></div>"""
    return layout("Admin · BookBot", body, extra_head='<meta name="robots" content="noindex">')


def not_found(msg="Page not found"):
    return layout("Not found · BookBot", nav() + f'<div class="wrap" style="padding:60px 20px"><h1>{e(msg)}</h1><p><a href="/">Back to BookBot</a></p></div>')
