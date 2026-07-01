/**
 * Leaflet map: registered collateral site vs field-photo GPS captures.
 */
(function (global) {
  'use strict';

  var DEFAULT_CENTER = [9.03, 38.74];
  var DEFAULT_ZOOM = 13;
  var maps = {};

  function siteIcon() {
    return L.divIcon({
      className: 'collateral-map-pin collateral-map-pin-site',
      html: '<span title="Registered site">📍</span>',
      iconSize: [28, 28],
      iconAnchor: [14, 28],
    });
  }

  function photoIcon(far) {
    return L.divIcon({
      className: 'collateral-map-pin collateral-map-pin-photo' + (far ? ' far' : ''),
      html: '<span title="Field photo">📷</span>',
      iconSize: [26, 26],
      iconAnchor: [13, 26],
    });
  }

  function popupHtml(marker) {
    var html = '<div class="collateral-map-popup"><strong>' + marker.label + '</strong>';
    html += '<br><small>' + marker.lat.toFixed(6) + ', ' + marker.lon.toFixed(6) + '</small>';
    if (marker.accuracy_m != null) {
      html += '<br><small>±' + Math.round(marker.accuracy_m) + ' m accuracy</small>';
    }
    if (marker.kind === 'photo' && marker.distance_m != null) {
      html += '<br><small>' + marker.distance_m + ' m from registered site</small>';
      if (marker.far_from_site) {
        html += '<br><em style="color:#c62828;">Outside verification radius</em>';
      }
    }
    if (marker.image_url) {
      html += '<br><a href="' + marker.image_url + '" target="_blank" rel="noopener"><img src="' + marker.image_url + '" alt="" style="max-width:120px;margin-top:4px;border-radius:4px;"></a>';
    }
    html += '</div>';
    return html;
  }

  function drawMarkers(map, layerGroup, data) {
    layerGroup.clearLayers();
    var bounds = [];
    (data.markers || []).forEach(function (m) {
      var latlng = [m.lat, m.lon];
      bounds.push(latlng);
      var icon = m.kind === 'site' ? siteIcon() : photoIcon(m.far_from_site);
      var layer = L.marker(latlng, { icon: icon }).bindPopup(popupHtml(m));
      layerGroup.addLayer(layer);
      if (m.accuracy_m && m.accuracy_m > 0) {
        layerGroup.addLayer(L.circle(latlng, {
          radius: m.accuracy_m,
          color: m.kind === 'site' ? '#1565c0' : '#2e7d32',
          fillOpacity: 0.08,
          weight: 1,
        }));
      }
      if (m.kind === 'site' && data.photo_count) {
        (data.markers || []).forEach(function (p) {
          if (p.kind === 'photo') {
            layerGroup.addLayer(L.polyline([[m.lat, m.lon], [p.lat, p.lon]], {
              color: p.far_from_site ? '#c62828' : '#66bb6a',
              dashArray: p.far_from_site ? '6 4' : '4 6',
              weight: 2,
              opacity: 0.7,
            }));
          }
        });
      }
    });
    if (bounds.length === 1) {
      map.setView(bounds[0], 17);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });
    }
  }

  function init(container, data, mapKey) {
    if (!container || !global.L) return null;
    mapKey = mapKey || container.id || 'default';
    if (maps[mapKey]) {
      maps[mapKey].data = data;
      drawMarkers(maps[mapKey].map, maps[mapKey].layer, data);
      return maps[mapKey];
    }
    var map = L.map(container, { scrollWheelZoom: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);
    var layer = L.layerGroup().addTo(map);
    if (!data.markers || !data.markers.length) {
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    } else {
      drawMarkers(map, layer, data);
    }
    maps[mapKey] = { map: map, layer: layer, data: data };
    setTimeout(function () { map.invalidateSize(); }, 200);
    return maps[mapKey];
  }

  function readConfig(container) {
    var scriptId = container.getAttribute('data-config-id');
    if (!scriptId) return { markers: [] };
    var el = document.getElementById(scriptId);
    if (!el || !el.textContent) return { markers: [] };
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return { markers: [] };
    }
  }

  function updateLiveSite(mapKey, lat, lon, accuracy, label) {
    var entry = maps[mapKey];
    if (!entry) return;
    var data = JSON.parse(JSON.stringify(entry.data || { markers: [] }));
    data.markers = (data.markers || []).filter(function (m) { return m.kind !== 'site'; });
    if (lat != null && lon != null && !isNaN(lat) && !isNaN(lon)) {
      data.markers.unshift({
        kind: 'site',
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        label: label || 'Registered site (live)',
        accuracy_m: accuracy != null ? parseFloat(accuracy) : null,
      });
      data.has_site = true;
    }
    entry.data = data;
    drawMarkers(entry.map, entry.layer, data);
  }

  function boot() {
    if (!global.L) return;
    document.querySelectorAll('.collateral-map-canvas').forEach(function (canvas) {
      var data = readConfig(canvas);
      init(canvas, data, canvas.id);
    });
  }

  global.CollateralMap = {
    init: init,
    updateLiveSite: updateLiveSite,
    boot: boot,
  };

  document.addEventListener('DOMContentLoaded', boot);
  document.addEventListener('collateral:site-gps-updated', function (ev) {
    var d = ev.detail || {};
    if (d.mapId) {
      updateLiveSite(d.mapId, d.lat, d.lon, d.accuracy, d.label);
    }
  });
})(window);
