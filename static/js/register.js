/* Register page: click-to-pick location map + browser geolocation. */
(function () {
  'use strict';
  const latInput = document.getElementById('latitude');
  const lngInput = document.getElementById('longitude');
  const mapEl = document.getElementById('pick-map');
  const locateBtn = document.getElementById('locate');
  const start = [parseFloat(latInput.value) || 12.9716, parseFloat(lngInput.value) || 77.5946];

  let map = null, marker = null;
  if (window.L) {
    map = L.map('pick-map').setView(start, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    marker = L.marker(start, { draggable: true }).addTo(map);
  } else {
    mapEl.innerHTML = '<div class="map-error small">The map could not be loaded. Enter your latitude and longitude below, or use the GPS button.</div>';
  }

  function setPosition(lat, lng, pan) {
    latInput.value = lat.toFixed(6);
    lngInput.value = lng.toFixed(6);
    if (marker) { marker.setLatLng([lat, lng]); }
    if (map && pan) { map.flyTo([lat, lng], Math.max(map.getZoom(), 14), { duration: 0.8 }); }
  }

  if (map) {
    map.on('click', function (e) { setPosition(e.latlng.lat, e.latlng.lng, false); });
    marker.on('dragend', function () { const p = marker.getLatLng(); setPosition(p.lat, p.lng, false); });
  }

  function fromInputs() {
    const lat = parseFloat(latInput.value);
    const lng = parseFloat(lngInput.value);
    if (map && !isNaN(lat) && !isNaN(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
      marker.setLatLng([lat, lng]);
      map.panTo([lat, lng]);
    }
  }
  latInput.addEventListener('change', fromInputs);
  lngInput.addEventListener('change', fromInputs);

  locateBtn.addEventListener('click', function () {
    if (!navigator.geolocation) { window.FoodShare.toast('Geolocation is not supported by your browser.', 'warning'); return; }
    window.FoodShare.busy(locateBtn, true);
    navigator.geolocation.getCurrentPosition(function (pos) {
      window.FoodShare.busy(locateBtn, false);
      setPosition(pos.coords.latitude, pos.coords.longitude, true);
    }, function () {
      window.FoodShare.busy(locateBtn, false);
      window.FoodShare.toast('Could not get your location. Click the map or enter coordinates instead.', 'warning');
    }, { timeout: 10000 });
  });

  // role toggle: only donors have a pickup address
  const addressGroup = document.getElementById('address-group');
  function syncRole() {
    const checked = document.querySelector('input[name="role"]:checked');
    if (addressGroup && checked) { addressGroup.hidden = checked.value !== 'Donor'; }
  }
  document.querySelectorAll('input[name="role"]').forEach(function (r) { r.addEventListener('change', syncRole); });
  syncRole();
})();
