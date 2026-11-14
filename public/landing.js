(function () {
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function post(url, data) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
      .then(function (r) { return r.json().then(function (j) { j._status = r.status; return j; }); });
  }
  var f = $('onb'), res = $('res'), go = $('go');
  if (f) f.onsubmit = function (ev) {
    ev.preventDefault();
    var url = $('url').value.trim(); if (!url) return;
    go.disabled = true; var t0 = Date.now(), steps = ['Opening your website…', 'Reading services and prices…', 'Finding opening hours and contact details…', 'Training your assistant…'], i = 0;
    res.className = 'result'; res.style.display = 'block'; res.innerHTML = '<b>' + steps[0] + '</b>';
    var timer = setInterval(function () { i = Math.min(i + 1, steps.length - 1); res.innerHTML = '<b>' + steps[i] + '</b> <span class="small">' + Math.round((Date.now() - t0) / 1000) + 's</span>'; }, 3000);
    post('/api/onboard', { url: url }).then(function (r) {
      clearInterval(timer); go.disabled = false;
      if (!r.ok) { res.className = 'result err'; res.innerHTML = '<b>' + esc(r.error || 'Something went wrong') + '</b>'; return; }
      var s = (Date.now() - t0) / 1000;
      var warn = r.quality === 'failed' ? '<p class="notice">We could not read your website (' + esc(r.notes) + '). Your assistant is ready, but add your details in the edit form so it can answer properly.</p>'
        : (r.quality === 'poor' ? '<p class="notice">We could only read a little from your website. Add your services and hours in the edit form for better answers.</p>' : '');
      res.innerHTML = '<span class="pill ' + esc(r.quality) + '">' + esc(r.quality) + ' scrape</span> <span class="small">ready in ' + s.toFixed(1) + 's</span>' +
        '<h3 style="margin:8px 0">Your assistant for ' + esc(r.name) + ' is ready</h3>' + warn +
        '<p><a class="btn" href="' + esc(r.demo_url) + '" target="_blank">Open my demo</a> <a class="btn ghost" href="' + esc(r.edit_url) + '" target="_blank">Edit details</a></p>' +
        '<p class="small">Public demo link (share it with anyone): <a href="' + esc(r.demo_url) + '">' + esc(r.demo_url) + '</a></p>' +
        '<p class="small"><b>Your private dashboard</b> (bookmark it, don\'t share it): <a href="' + esc(r.dashboard_url) + '">' + esc(r.dashboard_url) + '</a></p>';
    }).catch(function () { clearInterval(timer); go.disabled = false; res.className = 'result err'; res.innerHTML = '<b>Connection problem, please try again.</b>'; });
  };
  document.querySelectorAll('.plan-btn').forEach(function (b) {
    b.addEventListener('click', function () { var s = document.querySelector('#setupf select[name=plan]'); if (s) s.value = b.dataset.plan; });
  });
  var sf = $('setupf');
  if (sf) sf.onsubmit = function (ev) {
    ev.preventDefault(); var d = {}; new FormData(sf).forEach(function (v, k) { d[k] = v; });
    var btn = sf.querySelector('button'); btn.disabled = true;
    post('/api/setup-request', d).then(function (r) {
      btn.disabled = false; $('setupmsg').textContent = r.message || r.error || '';
      if (r.ok) sf.reset();
    }).catch(function () { btn.disabled = false; $('setupmsg').textContent = 'Connection problem, please try again.'; });
  };
})();
