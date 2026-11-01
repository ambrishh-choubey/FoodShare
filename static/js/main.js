/* FoodShare - shared JavaScript: API client (CSRF aware), toasts, confirm
   dialogs, form validation, theme, animations. */
(function () {
  'use strict';

  // ------------------------------------------------------------- helpers
  function esc(value) {
    const d = document.createElement('div');
    d.textContent = value == null ? '' : String(value);
    return d.innerHTML;
  }

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  async function api(path, options) {
    const opts = Object.assign({ method: 'GET', headers: {}, credentials: 'same-origin' }, options || {});
    opts.headers = Object.assign({ Accept: 'application/json' }, opts.headers);
    if (opts.method.toUpperCase() !== 'GET') { opts.headers['X-CSRFToken'] = csrfToken(); }
    if (opts.body && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
      opts.headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
      res = await fetch('/api/v1' + path, opts);
    } catch (e) {
      throw { code: 'network', message: 'Cannot reach the server. Check your connection and try again.' };
    }
    let json = null;
    try { json = await res.json(); } catch (e) { /* non-JSON response */ }
    if (!res.ok || !json || json.success === false) {
      const err = (json && json.error) || { code: 'http_' + res.status, message: 'Request failed (HTTP ' + res.status + ').' };
      if (res.status === 401 && !document.body.classList.contains('bg-auth')) {
        err.message = 'Your session has expired. Redirecting to login...';
        toast(err.message, 'warning');
        setTimeout(function () { window.location.href = '/login'; }, 1500);
      }
      throw err;
    }
    return json;
  }

  function toast(message, type) {
    const area = document.getElementById('toast-area');
    if (!area || !window.bootstrap) { window.alert(message); return; }
    const kind = type || 'success';
    const icons = { success: 'check-circle-fill', danger: 'exclamation-octagon-fill', warning: 'exclamation-triangle-fill', info: 'info-circle-fill' };
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + kind + ' border-0';
    el.setAttribute('role', 'alert');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"><i class="bi bi-' + (icons[kind] || icons.info) + ' me-2"></i>' +
      esc(message) + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    area.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 5000 });
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
    t.show();
  }

  /* Bootstrap modal confirm -> Promise<boolean>. Falls back to window.confirm. */
  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      const el = document.getElementById('confirm-modal');
      if (!el || !window.bootstrap) { resolve(window.confirm(opts.message || 'Are you sure?')); return; }
      el.querySelector('#confirm-title').textContent = opts.title || 'Are you sure?';
      el.querySelector('#confirm-body').textContent = opts.message || '';
      const ok = el.querySelector('#confirm-ok');
      ok.textContent = opts.confirmText || 'Confirm';
      ok.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-fs');
      const modal = bootstrap.Modal.getOrCreateInstance(el);
      let result = false;
      function onOk() { result = true; modal.hide(); }
      function onHidden() {
        ok.removeEventListener('click', onOk);
        el.removeEventListener('hidden.bs.modal', onHidden);
        resolve(result);
      }
      ok.addEventListener('click', onOk);
      el.addEventListener('hidden.bs.modal', onHidden);
      modal.show();
    });
  }

  /* Disable a button and show a spinner while an action runs. */
  function busy(btn, on) {
    if (!btn) { return; }
    if (on) {
      btn.dataset.html = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' +
        (btn.dataset.busyText || 'Working...');
    } else {
      if (btn.dataset.html) { btn.innerHTML = btn.dataset.html; }
      btn.disabled = false;
    }
  }

  function spinnerBlock(text) {
    return '<div class="loading-block" role="status"><span class="spinner-border text-success" aria-hidden="true"></span><span>' + esc(text || 'Loading...') + '</span></div>';
  }

  /* Friendly inline error with a Retry button. */
  function showError(container, message, onRetry) {
    container.innerHTML = '<div class="error-block" role="alert"><i class="bi bi-wifi-off"></i><div class="fw-semibold">Something went wrong</div>' +
      '<div class="small mb-2">' + esc(message) + '</div>' +
      (onRetry ? '<button type="button" class="btn btn-sm btn-outline-danger" data-retry>Try again</button>' : '') + '</div>';
    const btn = container.querySelector('[data-retry]');
    if (btn && onRetry) { btn.addEventListener('click', onRetry); }
  }

  function fmtDateTime(iso) {
    if (!iso) { return '-'; }
    return new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function timeLeft(iso) {
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) { return { text: 'Expired', urgent: true }; }
    const mins = Math.floor(ms / 60000);
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return { text: (h ? h + 'h ' : '') + m + 'm left', urgent: mins < 60 };
  }

  function refreshCountdowns(scope) {
    (scope || document).querySelectorAll('.countdown[data-expires]').forEach(function (el) {
      const r = timeLeft(el.getAttribute('data-expires'));
      el.textContent = r.text;
      el.classList.toggle('urgent', r.urgent);
    });
  }

  function statusBadge(status) {
    const map = {
      Pending: ['warning text-dark', 'hourglass-split', 'Pending'],
      Claimed: ['info text-dark', 'bag-check', 'Claimed'],
      Picked_Up: ['success', 'check2-all', 'Picked up']
    };
    const s = map[status] || ['secondary', 'question', status];
    return '<span class="badge bg-' + s[0] + '"><i class="bi bi-' + s[1] + ' me-1"></i>' + esc(s[2]) + '</span>';
  }

  window.FoodShare = {
    esc: esc, api: api, toast: toast, confirm: confirmDialog, busy: busy,
    spinnerBlock: spinnerBlock, showError: showError, fmtDateTime: fmtDateTime,
    timeLeft: timeLeft, refreshCountdowns: refreshCountdowns, statusBadge: statusBadge
  };

  // ------------------------------------- form validation + data-confirm
  // Capture phase so it runs before any page script's submit handler.
  document.addEventListener('submit', function (e) {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) { return; }
    if (form.dataset.confirmed) { delete form.dataset.confirmed; return; }

    if (form.classList.contains('needs-validation')) {
      form.classList.add('was-validated');
      if (!form.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
        const first = form.querySelector(':invalid');
        if (first) { first.focus(); }
        return;
      }
    }
    const message = form.getAttribute('data-confirm');
    if (message) {
      e.preventDefault();
      e.stopPropagation();
      const submitter = e.submitter;
      confirmDialog({
        title: form.getAttribute('data-confirm-title') || 'Please confirm',
        message: message,
        confirmText: form.getAttribute('data-confirm-ok') || 'Confirm',
        danger: form.hasAttribute('data-confirm-danger')
      }).then(function (yes) {
        if (!yes) { return; }
        form.dataset.confirmed = '1';
        if (form.requestSubmit) { form.requestSubmit(submitter || undefined); } else { form.submit(); }
      });
    }
  }, true);

  // Re-enable Bootstrap-style inline validity feedback while typing.
  document.addEventListener('input', function (e) {
    const form = e.target.form;
    if (form && form.classList.contains('was-validated')) { /* styles update automatically */ }
  });

  // --------------------------------------------------------------- theme
  const root = document.documentElement;
  const themeBtn = document.getElementById('theme-toggle');
  function paintThemeIcon() {
    if (!themeBtn) { return; }
    const dark = root.getAttribute('data-bs-theme') === 'dark';
    themeBtn.innerHTML = '<i class="bi bi-' + (dark ? 'sun-fill' : 'moon-stars-fill') + '"></i>';
    themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-bs-theme', next);
      try { localStorage.setItem('fs-theme', next); } catch (e) { /* storage unavailable */ }
      paintThemeIcon();
    });
    paintThemeIcon();
  }

  // ------------------------------------------------- navbar shadow on scroll
  const nav = document.querySelector('.fs-nav');
  function onScroll() { if (nav) { nav.classList.toggle('scrolled', window.scrollY > 8); } }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // ------------------------------------------------------ scroll reveal
  const reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.15 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add('in'); });
  }

  // ------------------------------------------------------ number counters
  function animateCount(el, to) {
    const from = parseInt(el.textContent, 10) || 0;
    if (from === to) { el.textContent = to; return; }
    const start = performance.now();
    const dur = 1100;
    (function step(now) {
      const p = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(from + (to - from) * eased);
      if (p < 1) { requestAnimationFrame(step); }
    })(start);
  }
  const statEls = document.querySelectorAll('[data-stat]');
  if (statEls.length) {
    statEls.forEach(function (el) {
      const target = parseInt(el.getAttribute('data-count'), 10) || 0;
      if ('IntersectionObserver' in window) {
        el.textContent = '0';
        const o = new IntersectionObserver(function (entries) {
          entries.forEach(function (e) { if (e.isIntersecting) { animateCount(el, target); o.disconnect(); } });
        }, { threshold: 0.4 });
        o.observe(el);
      } else { el.textContent = target; }
    });
    setInterval(function () {
      if (document.hidden) { return; }
      api('/stats').then(function (res) {
        statEls.forEach(function (el) {
          const v = res.data[el.getAttribute('data-stat')];
          if (typeof v === 'number') { animateCount(el, v); }
        });
      }).catch(function () { /* ignore background errors */ });
    }, 30000);
  }

  // ------------------------------------------------------- typed headline
  document.querySelectorAll('[data-typed]').forEach(function (el) {
    let words;
    try { words = JSON.parse(el.getAttribute('data-typed')); } catch (e) { return; }
    if (!words || !words.length) { return; }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = words[0]; return; }
    let w = 0, i = 0, deleting = false;
    (function tick() {
      const word = words[w];
      el.textContent = word.slice(0, i);
      let delay = deleting ? 45 : 85;
      if (!deleting && i === word.length) { deleting = true; delay = 1500; }
      else if (deleting && i === 0) { deleting = false; w = (w + 1) % words.length; delay = 350; }
      i += deleting ? -1 : 1;
      setTimeout(tick, delay);
    })();
  });

  // ------------------------------------------- live table filter (admin)
  document.querySelectorAll('input[data-filter-table]').forEach(function (input) {
    const table = document.getElementById(input.getAttribute('data-filter-table'));
    if (!table) { return; }
    input.addEventListener('input', function () {
      const q = input.value.trim().toLowerCase();
      table.querySelectorAll('tbody tr').forEach(function (tr) {
        tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) === -1;
      });
    });
  });

  // -------------------------------------------------- password visibility
  document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const input = document.getElementById(btn.getAttribute('data-toggle-password'));
      if (!input) { return; }
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = '<i class="bi bi-' + (show ? 'eye-slash' : 'eye') + '"></i>';
    });
  });

  // ------------------------------------------- countdown ticker (30s)
  refreshCountdowns();
  setInterval(function () { refreshCountdowns(); }, 30000);

  // ------------------------------------- warn when core libraries failed
  window.addEventListener('load', function () {
    if (!window.bootstrap) {
      const warn = document.createElement('div');
      warn.className = 'alert alert-warning m-3';
      warn.textContent = 'Some page resources could not be loaded (check your internet connection). Parts of the interface may not work until you reload.';
      document.body.insertBefore(warn, document.body.firstChild);
    }
  });
})();
