/* BookBot chat widget. Embed: <script src="https://YOUR-DOMAIN/widget.js" data-bot="your-slug" defer></script> */
(function () {
  var me = document.currentScript || document.querySelector('script[data-bot][src*="widget.js"]');
  if (!me || window.__bookbot) return; window.__bookbot = 1;
  var slug = me.getAttribute('data-bot'), base = new URL(me.src, location.href).origin, autoOpen = me.getAttribute('data-open') === '1';
  var C = { name: 'us', color: '#4f46e5', services: [] }, history = [], formShown = false, ready, pending = [];
  function api(path, body) {
    return fetch(base + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
      .then(function (r) { return r.json(); });
  }
  var host = document.createElement('div'); host.id = 'bookbot-widget'; document.body.appendChild(host);
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
  root.innerHTML = '<style>' +
    ':host{all:initial}*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}' +
    '.fab{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:0;color:#fff;font-size:26px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25);z-index:2147483000}' +
    '.panel{position:fixed;right:20px;bottom:92px;width:370px;max-width:calc(100vw - 24px);height:560px;max-height:calc(100vh - 110px);background:#fff;border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;z-index:2147483000}' +
    '.panel.open{display:flex}.hd{color:#fff;padding:14px 16px}.hd b{display:block;font-size:16px}.hd small{opacity:.85;font-size:12px}' +
    '.log{flex:1;overflow:auto;padding:14px;background:#f8fafc;font-size:14px;line-height:1.45}.m{max-width:85%;padding:9px 12px;border-radius:14px;margin:6px 0;white-space:pre-wrap;word-wrap:break-word}' +
    '.bot{background:#fff;border:1px solid #e2e8f0;color:#0f172a}.me{color:#fff;margin-left:auto}.typing{opacity:.6}' +
    'form.in{display:flex;border-top:1px solid #e2e8f0}form.in input{flex:1;border:0;padding:14px;font-size:14px;outline:none}form.in button{border:0;background:none;font-weight:700;padding:0 16px;cursor:pointer}' +
    '.bk{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:12px;margin:8px 0}.bk b{font-size:14px}.bk input,.bk select{width:100%;margin-top:7px;padding:9px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;background:#fff}' +
    '.bk button{margin-top:10px;width:100%;padding:10px;border:0;border-radius:8px;color:#fff;font-weight:700;cursor:pointer;font-size:14px}.bk small{display:block;color:#64748b;margin-top:6px;font-size:11px}' +
    '.qr{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 10px;background:#f8fafc}.qr button{border:1px solid #cbd5e1;background:#fff;border-radius:99px;padding:6px 10px;font-size:12px;cursor:pointer}' +
    '.ft{font-size:10px;text-align:center;color:#94a3b8;padding:4px;background:#fff}.ft a{color:#94a3b8}' +
    '</style><button class="fab" aria-label="Chat with us">💬</button><div class="panel" role="dialog"><div class="hd"><b class="t">Chat</b><small>Ask a question or request a booking</small></div>' +
    '<div class="log"></div><div class="qr"></div><form class="in"><input placeholder="Type your question…" maxlength="500" aria-label="Message"><button>Send</button></form><div class="ft">Powered by <a href="' + base + '" target="_blank" rel="noopener">BookBot</a></div></div>';
  var $ = function (s) { return root.querySelector(s); }, panel = $('.panel'), log = $('.log'), inp = $('form.in input');
  function el(tag, cls, text) { var x = document.createElement(tag); if (cls) x.className = cls; if (text != null) x.textContent = text; return x; }
  function add(text, who) { var m = el('div', 'm ' + who, text); if (who === 'me') m.style.background = C.color; log.appendChild(m); log.scrollTop = 1e9; return m; }
  function open() { panel.classList.add('open'); setTimeout(function () { inp.focus(); }, 50); }
  $('.fab').onclick = function () { panel.classList.toggle('open'); if (panel.classList.contains('open')) inp.focus(); };
  function ask(q) {
    if (!ready) { pending.push(q); return; }
    open(); add(q, 'me'); history.push({ role: 'user', content: q });
    var t = add('…', 'bot typing');
    api('/api/chat', { bot: slug, message: q, history: history.slice(-8) }).then(function (r) {
      t.className = 'm bot'; t.textContent = r.answer || r.error || 'Sorry, something went wrong.';
      history.push({ role: 'assistant', content: t.textContent });
      if (r.booking) bookingForm(r.service);
    }).catch(function () { t.className = 'm bot'; t.textContent = 'Connection problem, please try again.'; });
  }
  $('form.in').onsubmit = function (e) { e.preventDefault(); var v = inp.value.trim(); if (v) { inp.value = ''; ask(v); } };
  function bookingForm(service) {
    if (formShown) return; formShown = true;
    var f = el('form', 'bk'); f.appendChild(el('b', null, 'Request a booking'));
    [['name', 'text', 'Your name', true], ['phone', 'tel', 'Phone number', true]].forEach(function (x) {
      var i = el('input'); i.name = x[0]; i.type = x[1]; i.placeholder = x[2]; i.required = x[3]; i.maxLength = 120; f.appendChild(i);
    });
    var sel = el('select'); sel.name = 'service';
    sel.appendChild(new Option('Service (optional)', ''));
    (C.services || []).forEach(function (s) { sel.appendChild(new Option(s, s)); }); sel.appendChild(new Option('Other / not sure', 'Other'));
    if (service) sel.value = service; f.appendChild(sel);
    var pt = el('input'); pt.name = 'preferred_time'; pt.placeholder = 'Preferred day/time (e.g. Tue morning)'; pt.maxLength = 120; f.appendChild(pt);
    var hp = el('input'); hp.name = 'website_url'; hp.tabIndex = -1; hp.autocomplete = 'off'; hp.style.cssText = 'position:absolute;left:-9999px;height:0;width:0;opacity:0'; f.appendChild(hp);
    var b = el('button', null, 'Send request'); b.style.background = C.color; f.appendChild(b);
    f.appendChild(el('small', null, 'The team will contact you to confirm. Your details are only shared with ' + C.name + '.'));
    f.onsubmit = function (e) {
      e.preventDefault(); b.disabled = true; var d = { bot: slug, page: location.href };
      Array.prototype.forEach.call(f.querySelectorAll('input,select'), function (i) { d[i.name] = i.value; });
      d.note = history.filter(function (h) { return h.role === 'user'; }).map(function (h) { return h.content; }).slice(-3).join(' | ');
      api('/api/booking', d).then(function (r) {
        if (r.ok) { f.replaceWith(add('✅ ' + r.message, 'bot')); formShown = false; }
        else { b.disabled = false; alert(r.error || 'Please check your details.'); }
      }).catch(function () { b.disabled = false; alert('Connection problem, please try again.'); });
    };
    log.appendChild(f); log.scrollTop = 1e9;
  }
  api('/api/bot/' + encodeURIComponent(slug)).then(function (c) {
    if (c.error) { add('This assistant is not available.', 'bot'); return; }
    C = c; ready = true;
    $('.fab').style.background = C.color; $('.hd').style.background = C.color; $('.t').textContent = C.name;
    $('form.in button').style.color = C.color;
    add(C.greeting, 'bot');
    var qr = $('.qr');
    (C.quick_replies || []).forEach(function (q) { var x = el('button', null, q); x.type = 'button'; x.onclick = function () { ask(q); }; qr.appendChild(x); });
    var bk = el('button', null, '📅 Book'); bk.type = 'button'; bk.onclick = function () { open(); bookingForm(); }; qr.appendChild(bk);
    if (autoOpen && window.innerWidth > 700) open();
    pending.splice(0).forEach(ask);
  }).catch(function () { add('Connection problem, please try again later.', 'bot'); });
  window.BookBot = { ask: ask, open: open, book: function () { open(); bookingForm(); } };
})();
