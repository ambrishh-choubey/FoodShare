/* API docs page: live "Try it" buttons and database badge. */
(function () {
  'use strict';
  const FS = window.FoodShare;

  document.querySelectorAll('[data-try]').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      const out = document.getElementById(btn.getAttribute('data-out'));
      btn.disabled = true;
      out.hidden = false;
      out.textContent = 'Loading...';
      try {
        const res = await fetch('/api/v1' + btn.getAttribute('data-try'), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        const json = await res.json();
        out.textContent = 'HTTP ' + res.status + '\n' + JSON.stringify(json, null, 2);
      } catch (e) {
        out.textContent = 'Request failed: ' + e.message;
      } finally {
        btn.disabled = false;
      }
    });
  });

  const badge = document.getElementById('live-db');
  if (badge) {
    FS.api('/health').then(function (res) {
      const d = res.data.database;
      badge.innerHTML = '<i class="bi bi-database-fill-check"></i> ' + FS.esc(d.engine.toUpperCase()) + ' &middot; ' + FS.esc(d.database);
    }).catch(function () { badge.textContent = 'API unreachable'; });
  }
})();
