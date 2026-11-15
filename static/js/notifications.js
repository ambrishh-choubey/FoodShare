/* Navbar notification bell: unread badge, list, mark as read. */
(function () {
  'use strict';
  const FS = window.FoodShare;
  const list = document.getElementById('notif-list');
  const badge = document.getElementById('notif-count');
  const readAll = document.getElementById('notif-readall');
  if (!FS || !list || !badge) { return; }

  const ICONS = { claimed: 'bag-check', picked_up: 'check2-all', expired: 'alarm',
                  expiring: 'hourglass-split', pickup_due: 'truck' };

  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 1) { return 'just now'; }
    if (mins < 60) { return mins + ' min ago'; }
    if (mins < 1440) { return Math.round(mins / 60) + ' h ago'; }
    return FS.fmtDateTime(iso);
  }

  function item(n) {
    return '<button type="button" class="notif-item' + (n.read ? '' : ' unread') + '" data-id="' + n.id + '" data-read="' + (n.read ? '1' : '0') + '">' +
      '<i class="bi bi-' + (ICONS[n.kind] || 'bell') + '"></i><span>' + FS.esc(n.message) +
      '<small>' + FS.esc(ago(n.created_at)) + '</small></span></button>';
  }

  function render(rows, unread) {
    badge.textContent = unread > 99 ? '99+' : unread;
    badge.hidden = unread === 0;
    readAll.hidden = unread === 0;
    list.innerHTML = rows.length ? rows.map(item).join('')
      : '<div class="text-muted small p-3 text-center"><i class="bi bi-bell-slash d-block fs-4 mb-1"></i>No notifications yet.</div>';
  }

  async function load() {
    try {
      const res = await FS.api('/notifications?limit=15');
      render(res.data, (res.meta && res.meta.unread) || 0);
    } catch (e) { /* keep the last list; the next poll will retry */ }
  }

  list.addEventListener('click', async function (e) {
    const btn = e.target.closest('.notif-item');
    if (!btn || btn.dataset.read === '1') { return; }
    try { await FS.api('/notifications/' + btn.dataset.id + '/read', { method: 'POST' }); } catch (err) { FS.toast(err.message, 'warning'); }
    load();
  });

  readAll.addEventListener('click', async function () {
    try { await FS.api('/notifications/read-all', { method: 'POST' }); } catch (err) { FS.toast(err.message, 'warning'); }
    load();
  });

  const btn = document.getElementById('notif-btn');
  if (btn) { btn.addEventListener('show.bs.dropdown', load); }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { load(); } });
  setInterval(function () { if (!document.hidden) { load(); } }, 30000);
  load();
})();
