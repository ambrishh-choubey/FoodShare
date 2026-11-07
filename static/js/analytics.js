/* Impact page: draws Chart.js charts from the numbers the server calculated. */
(function () {
  'use strict';

  let data;
  try { data = JSON.parse(document.getElementById('boot').textContent); } catch (e) { return; }

  const canvases = document.querySelectorAll('canvas[id^="chart-"]');
  if (!canvases.length) { return; }  // the server already rendered an empty state

  if (!window.Chart) {
    canvases.forEach(function (c) {
      c.parentElement.innerHTML = '<div class="map-error small">Charts could not be loaded (check your internet connection). The numbers above are still correct.</div>';
    });
    return;
  }

  const COLORS = { available: '#f59e0b', claimed: '#0ea5e9', completed: '#16a34a', withdrawn: '#94a3b8', expired: '#ef4444' };
  const root = document.documentElement;
  const charts = [];

  function theme() {
    const dark = root.getAttribute('data-bs-theme') === 'dark';
    return {
      text: dark ? '#e6f2ea' : '#14281d',
      grid: dark ? 'rgba(255,255,255,.12)' : 'rgba(0,0,0,.08)',
      ring: dark ? '#13201a' : '#ffffff'
    };
  }

  function empty(el) {
    el.parentElement.innerHTML = '<div class="empty-state"><i class="bi bi-pie-chart"></i>No data yet</div>';
  }

  function hasData(values) { return values.some(function (v) { return v > 0; }); }

  function doughnut(id, labels, values, colors, t) {
    const el = document.getElementById(id);
    if (!el) { return; }
    if (!hasData(values)) { empty(el); return; }
    charts.push(new Chart(el, {
      type: 'doughnut',
      data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderColor: t.ring, borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '60%',
        plugins: { legend: { position: 'bottom', labels: { color: t.text } } }
      }
    }));
  }

  function bars(id, labels, values, label, t) {
    const el = document.getElementById(id);
    if (!el) { return; }
    if (!hasData(values)) { empty(el); return; }
    charts.push(new Chart(el, {
      type: 'bar',
      data: { labels: labels, datasets: [{ label: label, data: values, backgroundColor: COLORS.completed, borderRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: t.text }, grid: { color: t.grid } },
          y: { beginAtZero: true, ticks: { precision: 0, color: t.text }, grid: { color: t.grid } }
        }
      }
    }));
  }

  function draw() {
    charts.splice(0).forEach(function (c) { c.destroy(); });
    const t = theme();
    Chart.defaults.color = t.text;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    const L = data.listings;
    if (L) {
      doughnut('chart-status', ['Available', 'Awaiting pickup', 'Completed', 'Withdrawn', 'Expired'],
        [L.available, L.claimed, L.completed, L.withdrawn, L.expired],
        [COLORS.available, COLORS.claimed, COLORS.completed, COLORS.withdrawn, COLORS.expired], t);
    }
    if (data.activity) {
      bars('chart-activity', data.activity.labels.map(function (d) { return d.slice(5); }),
        data.activity.values, 'Donations posted', t);
    }
    if (data.claims) {
      doughnut('chart-pickups', ['Completed pickups', 'Pending pickups'],
        [data.claims.completed, data.claims.pending_pickups], [COLORS.completed, COLORS.claimed], t);
    }
    if (data.users) {
      doughnut('chart-ngos', ['Approved NGOs', 'Pending approval'],
        [data.users.ngos_approved, data.users.ngos_pending], [COLORS.completed, COLORS.available], t);
    }
  }

  draw();
  // Redraw with the right colours whenever the theme toggle is used.
  new MutationObserver(draw).observe(root, { attributes: true, attributeFilter: ['data-bs-theme'] });
})();