/* NGO dashboard: Leaflet map + live listing cards, claim via the JSON API.
   Before a claim only an APPROXIMATE area is shown; exact pickup details
   appear only in "My claimed pickups" once this NGO has claimed the food. */
(function () {
  'use strict';
  const FS = window.FoodShare;
  const listEl = document.getElementById('listing-cards');
  const mineEl = document.getElementById('mine-rows');
  const listError = document.getElementById('list-error');
  const radiusForm = document.getElementById('radius-form');
  const radiusInput = document.getElementById('radius');
  const mapEl = document.getElementById('map');

  let boot;
  try { boot = JSON.parse(document.getElementById('boot').textContent); } catch (e) { boot = null; }
  const me = boot ? boot.me : { name: '', latitude: 12.9716, longitude: 77.5946 };
  let radius = boot ? boot.radius : 50;
  let nearby = boot ? boot.nearby : [];
  let mine = boot ? boot.mine : [];

  // ----------------------------------------------------------------- map
  const mapOk = !!window.L;
  let map = null, markerLayer = null, circle = null, tileWarned = false;
  const markerByKey = {};
  let pinIcon = null;

  function groupKey(l) { return l.donor.latitude + ',' + l.donor.longitude; }

  if (mapOk) {
    try {
      map = L.map('map').setView([me.latitude, me.longitude], 12);
      const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(map);
      tiles.on('tileerror', function () {
        if (!tileWarned) { tileWarned = true; FS.toast('Map tiles could not be loaded. Check your connection - the list still works.', 'warning'); }
      });
      L.marker([me.latitude, me.longitude], {
        icon: L.divIcon({ className: 'fs-me', html: '<span></span>', iconSize: [18, 18] }),
        zIndexOffset: 1000
      }).addTo(map).bindPopup('<b>Your location</b><br>' + FS.esc(me.name));
      markerLayer = L.layerGroup().addTo(map);
      pinIcon = L.divIcon({ className: 'fs-pin', html: '<span><i class="bi bi-basket2-fill"></i></span>', iconSize: [38, 38], iconAnchor: [19, 38], popupAnchor: [0, -36] });
    } catch (e) {
      map = null;
    }
  }
  if (!map) {
    mapEl.innerHTML = '<div class="map-error"><i class="bi bi-map"></i><div class="fw-semibold">The map could not be loaded</div>' +
      '<div class="small">The map library failed to load (check your internet connection and reload). You can still claim food from the list.</div></div>';
  }

  function popupHtml(group) {
    return '<div class="fw-bold mb-1">' + FS.esc(group[0].donor.name) + '</div>' +
      '<div class="small text-muted mb-1"><i class="bi bi-shield-lock"></i> Approximate area only. The exact address is shared after you claim.</div>' +
      group.map(function (l) {
        return '<div class="popup-item"><div class="fw-semibold">' + FS.esc(l.food_type) + '</div>' +
          '<div class="small">' + FS.esc(l.quantity) + ' &middot; ~' + l.distance_km + ' km &middot; <span class="countdown" data-expires="' + FS.esc(l.expires_at) + '"></span></div>' +
          '<button class="btn btn-sm btn-fs mt-1" data-claim="' + l.id + '"><i class="bi bi-check2-circle"></i> Claim Food</button></div>';
      }).join('');
  }

  function drawMap(fit) {
    if (!map) { return; }
    markerLayer.clearLayers();
    Object.keys(markerByKey).forEach(function (k) { delete markerByKey[k]; });
    if (circle) { map.removeLayer(circle); }
    circle = L.circle([me.latitude, me.longitude], { radius: radius * 1000, color: '#16a34a', weight: 2, fillOpacity: 0.04, interactive: false }).addTo(map);

    const groups = {};
    nearby.forEach(function (l) { (groups[groupKey(l)] = groups[groupKey(l)] || []).push(l); });
    const pts = [[me.latitude, me.longitude]];
    Object.keys(groups).forEach(function (key) {
      const g = groups[key];
      const d = g[0].donor;
      // dashed circle = the area the donor is somewhere inside (not an exact point)
      L.circle([d.latitude, d.longitude], { radius: d.approximate_radius_m || 800, color: '#16a34a', weight: 1, dashArray: '4 4', fillOpacity: 0.1, interactive: false }).addTo(markerLayer);
      const marker = L.marker([d.latitude, d.longitude], { icon: pinIcon }).addTo(markerLayer);
      marker.bindPopup(popupHtml(g), { minWidth: 220 });
      marker.on('popupopen', function (ev) { FS.refreshCountdowns(ev.popup.getElement()); });
      markerByKey[key] = marker;
      pts.push([d.latitude, d.longitude]);
    });
    if (fit) {
      if (pts.length > 1) { map.fitBounds(pts, { padding: [50, 50], maxZoom: 14 }); }
      else { map.fitBounds(circle.getBounds()); }
    }
  }

  // ------------------------------------------------------------- listings
  function card(l, i) {
    return '<div class="listing-card" style="animation-delay:' + (i * 60) + 'ms">' +
      '<div class="d-flex justify-content-between align-items-start gap-2">' +
      '<div><div class="title">' + FS.esc(l.food_type) + '</div>' +
      '<div class="small text-muted"><i class="bi bi-shop me-1"></i>' + FS.esc(l.donor.name) + ' &middot; ' + FS.esc(l.quantity) + '</div></div>' +
      '<span class="badge bg-success-subtle text-success-emphasis text-nowrap"><i class="bi bi-geo-alt-fill"></i> ~' + l.distance_km + ' km</span></div>' +
      '<div class="d-flex justify-content-between align-items-center mt-2 gap-2 flex-wrap">' +
      '<span class="small"><i class="bi bi-clock me-1"></i><span class="countdown" data-expires="' + FS.esc(l.expires_at) + '"></span></span>' +
      '<div class="btn-group btn-group-sm">' +
      (map ? '<button class="btn btn-outline-secondary" data-locate="' + FS.esc(groupKey(l)) + '" title="Show area on map" aria-label="Show area on map"><i class="bi bi-crosshair"></i></button>' : '') +
      '<button class="btn btn-fs" data-claim="' + l.id + '"><i class="bi bi-check2-circle"></i> Claim Food</button></div></div></div>';
  }

  function mapsLink(d) {
    return 'https://www.openstreetmap.org/?mlat=' + encodeURIComponent(d.latitude) + '&mlon=' + encodeURIComponent(d.longitude) +
      '#map=17/' + encodeURIComponent(d.latitude) + '/' + encodeURIComponent(d.longitude);
  }

  function mineRow(l) {
    const d = l.donor;
    const action = l.status === 'Claimed'
      ? '<button class="btn btn-outline-success btn-sm" data-pickup="' + l.id + '" data-name="' + FS.esc(l.food_type) + '"><i class="bi bi-truck"></i> Mark picked up</button>' : '';
    const where = '<div>' + (d.address ? FS.esc(d.address) : '<span class="text-muted">No address given</span>') + '</div>' +
      '<a class="small" target="_blank" rel="noopener" href="' + mapsLink(d) + '"><i class="bi bi-geo-alt"></i> Open exact location</a>';
    return '<tr><td data-label="Food" class="fw-semibold">' + FS.esc(l.food_type) + '</td><td data-label="Quantity">' + FS.esc(l.quantity) +
      '</td><td data-label="Donor">' + FS.esc(d.name) + '<div class="small text-muted">' + FS.esc(d.email || '') + '</div></td>' +
      '<td data-label="Pickup details">' + where + '</td><td data-label="Status">' + FS.stageBadge(l) + FS.timeline(l) + '</td><td class="text-end">' + action + '</td></tr>';
  }

  function render(fit) {
    listError.hidden = true;
    document.getElementById('cnt-active').textContent = nearby.length;
    document.getElementById('cnt-mine').textContent = mine.filter(function (l) { return l.status === 'Claimed'; }).length;
    document.getElementById('cnt-radius').textContent = Math.round(radius);
    listEl.innerHTML = nearby.length ? nearby.map(card).join('')
      : '<div class="empty-state"><i class="bi bi-search-heart"></i>No active listings within ' + Math.round(radius) + ' km.<br>Try a larger radius.</div>';
    mineEl.innerHTML = mine.length ? mine.map(mineRow).join('')
      : '<tr class="empty-row"><td colspan="6"><div class="empty-state"><i class="bi bi-inbox"></i>You haven\'t claimed anything yet.</div></td></tr>';
    drawMap(fit);
    FS.refreshCountdowns(listEl);
  }

  async function load(fit, quiet) {
    try {
      const results = await Promise.all([
        FS.api('/listings?radius=' + encodeURIComponent(radius)),
        FS.api('/listings?scope=mine')
      ]);
      nearby = results[0].data;
      mine = results[1].data;
      render(fit);
    } catch (err) {
      if (!quiet) {
        listEl.innerHTML = '';
        listError.hidden = false;
        FS.showError(listError, err.message, function () {
          listError.hidden = true;
          listEl.innerHTML = FS.spinnerBlock('Loading nearby food...');
          load(true, false);
        });
      }
    }
  }

  async function act(path, btn) {
    FS.busy(btn, true);
    try {
      const res = await FS.api(path, { method: 'POST' });
      FS.toast(res.message, 'success');
      if (map) { map.closePopup(); }
    } catch (err) {
      const soft = err.code === 'already_claimed' || err.code === 'expired' || err.code === 'already_claimed_by_you';
      FS.toast(err.message, soft ? 'warning' : 'danger');
    }
    FS.busy(btn, false);
    load(false, true);
  }

  function findListing(id) {
    return nearby.filter(function (l) { return String(l.id) === String(id); })[0];
  }

  document.addEventListener('click', async function (e) {
    const claim = e.target.closest('[data-claim]');
    if (claim) {
      const l = findListing(claim.getAttribute('data-claim'));
      const yes = await FS.confirm({
        title: 'Claim this food?',
        message: l ? 'Claim "' + l.food_type + '" (' + l.quantity + ') from ' + l.donor.name + '? You are committing to collect it before it expires.' : 'Claim this listing?',
        confirmText: 'Yes, claim it'
      });
      if (yes) { act('/listings/' + claim.getAttribute('data-claim') + '/claim', claim); }
      return;
    }
    const pickup = e.target.closest('[data-pickup]');
    if (pickup) {
      const yes = await FS.confirm({
        title: 'Mark as picked up?',
        message: 'Confirm that you have collected "' + pickup.getAttribute('data-name') + '". This cannot be undone.',
        confirmText: 'Yes, picked up'
      });
      if (yes) { act('/listings/' + pickup.getAttribute('data-pickup') + '/pickup', pickup); }
      return;
    }
    const locate = e.target.closest('[data-locate]');
    if (locate && map) {
      const marker = markerByKey[locate.getAttribute('data-locate')];
      if (marker) {
        mapEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        map.flyTo(marker.getLatLng(), 14, { duration: 0.8 });
        marker.openPopup();
      }
    }
  });

  radiusForm.addEventListener('submit', function (e) {
    e.preventDefault();
    radius = Math.min(500, Math.max(1, parseFloat(radiusInput.value) || 50));
    radiusInput.value = Math.round(radius);
    listEl.innerHTML = FS.spinnerBlock('Searching within ' + Math.round(radius) + ' km...');
    load(true, false);
  });

  if (boot) { render(true); } else { load(true, false); }
  setInterval(function () { if (!document.hidden) { load(false, true); } }, 20000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { load(false, true); } });
})();
