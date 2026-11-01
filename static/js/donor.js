/* Donor dashboard: live table, AJAX posting/withdrawing via the JSON API. */
(function () {
  'use strict';
  const FS = window.FoodShare;
  const tbody = document.getElementById('donation-rows');
  const form = document.getElementById('donation-form');
  const errorBox = document.getElementById('donation-error');
  let known = {};
  let first = true;

  let boot;
  try {
    boot = JSON.parse(document.getElementById('boot').textContent);
  } catch (e) {
    boot = null;
  }

  function row(l) {
    const expires = l.status === 'Pending'
      ? '<span class="countdown" data-expires="' + FS.esc(l.expires_at) + '"></span>'
      : '<span class="text-muted">' + FS.esc(FS.fmtDateTime(l.expires_at)) + '</span>';
    const claimed = l.claimed_by ? '<i class="bi bi-building me-1"></i>' + FS.esc(l.claimed_by.name) : '<span class="text-muted">-</span>';
    const action = l.status === 'Pending'
      ? '<button class="btn btn-outline-danger btn-sm" data-withdraw="' + l.id + '" data-name="' + FS.esc(l.food_type) + '" aria-label="Withdraw listing"><i class="bi bi-trash"></i><span class="d-sm-none ms-1">Withdraw</span></button>' : '';
    const fresh = !first && known[l.id] !== l.status ? ' class="row-fresh"' : '';
    return '<tr' + fresh + '><td data-label="Food" class="fw-semibold">' + FS.esc(l.food_type) + '</td><td data-label="Quantity">' + FS.esc(l.quantity) +
      '</td><td data-label="Expires">' + expires + '</td><td data-label="Status">' + FS.statusBadge(l.status) +
      '</td><td data-label="Claimed by">' + claimed + '</td><td class="text-end">' + action + '</td></tr>';
  }

  function render(listings) {
    errorBox.hidden = true;
    if (!listings.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><i class="bi bi-basket"></i>No donations yet. Post your first surplus listing!</div></td></tr>';
    } else {
      tbody.innerHTML = listings.map(row).join('');
    }
    known = {};
    listings.forEach(function (l) { known[l.id] = l.status; });
    first = false;
    const count = function (s) { return listings.filter(function (l) { return l.status === s; }).length; };
    document.getElementById('cnt-pending').textContent = count('Pending');
    document.getElementById('cnt-claimed').textContent = count('Claimed');
    document.getElementById('cnt-picked').textContent = count('Picked_Up');
    FS.refreshCountdowns(tbody);
  }

  async function refresh(quiet) {
    try {
      const res = await FS.api('/listings');
      render(res.data);
    } catch (err) {
      if (!quiet || first) {
        tbody.innerHTML = '';
        errorBox.hidden = false;
        FS.showError(errorBox, err.message, function () {
          errorBox.hidden = true;
          tbody.innerHTML = '<tr><td colspan="6">' + FS.spinnerBlock('Loading your donations...') + '</td></tr>';
          refresh(false);
        });
      }
    }
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    // (main.js already blocked the event if the form was invalid)
    const btn = form.querySelector('button[type=submit]');
    FS.busy(btn, true);
    try {
      const res = await FS.api('/listings', {
        method: 'POST',
        body: {
          food_type: form.food_type.value,
          quantity: form.quantity.value,
          expiry_window: form.expiry_window.value
        }
      });
      FS.toast(res.message || 'Listing created.', 'success');
      form.reset();
      form.classList.remove('was-validated');
      form.expiry_window.value = 4;
      await refresh(true);
    } catch (err) {
      FS.toast(err.message, 'danger');
    } finally {
      FS.busy(btn, false);
    }
  });

  tbody.addEventListener('click', async function (e) {
    const btn = e.target.closest('[data-withdraw]');
    if (!btn) { return; }
    const yes = await FS.confirm({
      title: 'Withdraw this listing?',
      message: '"' + btn.getAttribute('data-name') + '" will be removed and NGOs will no longer see it.',
      confirmText: 'Withdraw', danger: true
    });
    if (!yes) { return; }
    FS.busy(btn, true);
    try {
      const res = await FS.api('/listings/' + btn.getAttribute('data-withdraw'), { method: 'DELETE' });
      FS.toast(res.message, 'info');
    } catch (err) {
      FS.toast(err.message, 'warning');
    }
    refresh(true);
  });

  if (boot) { render(boot.listings); } else { refresh(false); }
  setInterval(function () { if (!document.hidden) { refresh(true); } }, 15000);
})();
