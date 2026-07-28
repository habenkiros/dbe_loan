/**
 * Collateral location map.
 * - Gebeta tiles (Phase 2): MapLibre GL + Gebeta style JSON (Bearer API key)
 *   Docs: https://docs.gebeta.app/docs · https://github.com/AfriGebeta/gebeta-tiles-js
 * - Fallback: Leaflet + OpenStreetMap / Esri satellite
 */
(function (global) {
  'use strict';

  var DEFAULT_CENTER_LATLON = [9.03, 38.74];
  var DEFAULT_CENTER_LNGLAT = [38.74, 9.03];
  var DEFAULT_ZOOM = 13;
  var maps = {};

  function provider() {
    return global.COLLATERAL_MAP_PROVIDER || {};
  }

  function useGebeta() {
    var p = provider();
    return p.tiles === 'gebeta' && p.gebetaConfigured && p.apiKey && global.maplibregl;
  }

  function siteIconHtml() {
    return '<span class="collateral-map-pin collateral-map-pin-site" title="Registered site">📍</span>';
  }
  function declaredIconHtml(far) {
    return '<span class="collateral-map-pin collateral-map-pin-declared' + (far ? ' far' : '') + '" title="Declared address">🏠</span>';
  }
  function photoIconHtml(far) {
    return '<span class="collateral-map-pin collateral-map-pin-photo' + (far ? ' far' : '') + '" title="Field photo">📷</span>';
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
    if (marker.kind === 'declared_address') {
      if (marker.address_text) {
        html += '<br><small>' + marker.address_text + '</small>';
      }
      if (marker.distance_from_site_m != null) {
        html += '<br><small>' + marker.distance_from_site_m + ' m from field site</small>';
        if (marker.far_from_site) {
          html += '<br><em style="color:#c62828;">Far from declared address area</em>';
        }
      }
    }
    if (marker.image_url) {
      html += '<br><a href="' + marker.image_url + '" target="_blank" rel="noopener"><img src="' + marker.image_url + '" alt="" style="max-width:120px;margin-top:4px;border-radius:4px;"></a>';
    }
    html += '</div>';
    return html;
  }

  function circlePolygon(lon, lat, radiusM, steps) {
    steps = steps || 64;
    var coords = [];
    var latRad = (lat * Math.PI) / 180;
    var metersPerDegLat = 111320;
    var metersPerDegLon = 111320 * Math.cos(latRad);
    for (var i = 0; i <= steps; i++) {
      var a = (i / steps) * 2 * Math.PI;
      var dLat = (radiusM * Math.sin(a)) / metersPerDegLat;
      var dLon = (radiusM * Math.cos(a)) / metersPerDegLon;
      coords.push([lon + dLon, lat + dLat]);
    }
    return {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [coords] },
      properties: {},
    };
  }

  /* ---------- Leaflet backend ---------- */

  function leafletSiteIcon() {
    return L.divIcon({
      className: 'collateral-map-pin-wrap',
      html: siteIconHtml(),
      iconSize: [28, 28],
      iconAnchor: [14, 28],
    });
  }
  function leafletDeclaredIcon(far) {
    return L.divIcon({
      className: 'collateral-map-pin-wrap',
      html: declaredIconHtml(far),
      iconSize: [26, 26],
      iconAnchor: [13, 26],
    });
  }
  function leafletPhotoIcon(far) {
    return L.divIcon({
      className: 'collateral-map-pin-wrap',
      html: photoIconHtml(far),
      iconSize: [26, 26],
      iconAnchor: [13, 26],
    });
  }

  function drawLeafletMarkers(map, layerGroup, data) {
    layerGroup.clearLayers();
    var bounds = [];
    (data.markers || []).forEach(function (m) {
      var latlng = [m.lat, m.lon];
      bounds.push(latlng);
      var icon;
      if (m.kind === 'site') icon = leafletSiteIcon();
      else if (m.kind === 'declared_address') icon = leafletDeclaredIcon(m.far_from_site);
      else icon = leafletPhotoIcon(m.far_from_site);
      layerGroup.addLayer(L.marker(latlng, { icon: icon }).bindPopup(popupHtml(m)));
      if (m.accuracy_m && m.accuracy_m > 0) {
        layerGroup.addLayer(L.circle(latlng, {
          radius: m.accuracy_m,
          color: m.kind === 'site' ? '#1565c0' : (m.kind === 'declared_address' ? '#6a1b9a' : '#2e7d32'),
          fillOpacity: 0.08,
          weight: 1,
        }));
      }
      if (m.kind === 'site') {
        (data.markers || []).forEach(function (p) {
          if (p.kind === 'photo') {
            layerGroup.addLayer(L.polyline([[m.lat, m.lon], [p.lat, p.lon]], {
              color: p.far_from_site ? '#c62828' : '#66bb6a',
              dashArray: p.far_from_site ? '6 4' : '4 6',
              weight: 2,
              opacity: 0.7,
            }));
          }
          if (p.kind === 'declared_address' && p.lat != null) {
            layerGroup.addLayer(L.polyline([[m.lat, m.lon], [p.lat, p.lon]], {
              color: p.far_from_site ? '#e65100' : '#9575cd',
              dashArray: '8 4',
              weight: 2,
              opacity: 0.75,
            }));
          }
        });
      }
    });
    if (bounds.length === 1) map.setView(bounds[0], 17);
    else if (bounds.length > 1) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });
  }

  function initLeaflet(container, data, mapKey) {
    if (!global.L) return null;
    var map = L.map(container, { scrollWheelZoom: true });
    var street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    });
    var satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles &copy; Esri', maxZoom: 19 }
    );
    street.addTo(map);
    L.control.layers(
      { 'Street map': street, 'Satellite': satellite },
      null,
      { collapsed: true, position: 'topright' }
    ).addTo(map);
    var layer = L.layerGroup().addTo(map);
    if (!data.markers || !data.markers.length) map.setView(DEFAULT_CENTER_LATLON, DEFAULT_ZOOM);
    else drawLeafletMarkers(map, layer, data);
    maps[mapKey] = { engine: 'leaflet', map: map, layer: layer, data: data, markers: [] };
    setTimeout(function () { map.invalidateSize(); }, 200);
    return maps[mapKey];
  }

  /* ---------- Gebeta / MapLibre backend ---------- */

  function gebetaTransformRequest(url, resourceType) {
    var key = provider().apiKey;
    if (!key) return { url: url };
    if (url.indexOf('tiles.gebeta.app') !== -1 || url.indexOf('gebeta.app') !== -1) {
      return {
        url: url,
        headers: { Authorization: 'Bearer ' + key },
      };
    }
    return { url: url };
  }

  function clearGebetaOverlays(entry) {
    (entry.domMarkers || []).forEach(function (mk) {
      try { mk.remove(); } catch (e) { /* ignore */ }
    });
    entry.domMarkers = [];
    var map = entry.map;
    ['collateral-lines', 'collateral-circles'].forEach(function (id) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    });
  }

  function drawGebetaMarkers(entry, data) {
    var map = entry.map;
    clearGebetaOverlays(entry);
    var bounds = new maplibregl.LngLatBounds();
    var hasBound = false;
    var lineFeatures = [];
    var circleFeatures = [];
    var site = null;

    (data.markers || []).forEach(function (m) {
      if (m.kind === 'site') site = m;
    });

    (data.markers || []).forEach(function (m) {
      var el = document.createElement('div');
      el.className = 'collateral-map-marker-el';
      if (m.kind === 'site') el.innerHTML = siteIconHtml();
      else if (m.kind === 'declared_address') el.innerHTML = declaredIconHtml(m.far_from_site);
      else el.innerHTML = photoIconHtml(m.far_from_site);

      var marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([m.lon, m.lat])
        .setPopup(new maplibregl.Popup({ offset: 18 }).setHTML(popupHtml(m)))
        .addTo(map);
      entry.domMarkers.push(marker);
      bounds.extend([m.lon, m.lat]);
      hasBound = true;

      if (m.accuracy_m && m.accuracy_m > 0) {
        var color = m.kind === 'site' ? '#1565c0' : (m.kind === 'declared_address' ? '#6a1b9a' : '#2e7d32');
        var feat = circlePolygon(m.lon, m.lat, m.accuracy_m);
        feat.properties = { color: color };
        circleFeatures.push(feat);
      }

      if (site && m !== site) {
        if (m.kind === 'photo') {
          lineFeatures.push({
            type: 'Feature',
            properties: { color: m.far_from_site ? '#c62828' : '#66bb6a', dash: m.far_from_site ? [6, 4] : [4, 6] },
            geometry: { type: 'LineString', coordinates: [[site.lon, site.lat], [m.lon, m.lat]] },
          });
        }
        if (m.kind === 'declared_address') {
          lineFeatures.push({
            type: 'Feature',
            properties: { color: m.far_from_site ? '#e65100' : '#9575cd', dash: [8, 4] },
            geometry: { type: 'LineString', coordinates: [[site.lon, site.lat], [m.lon, m.lat]] },
          });
        }
      }
    });

    map.addSource('collateral-circles', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: circleFeatures },
    });
    map.addLayer({
      id: 'collateral-circles',
      type: 'fill',
      source: 'collateral-circles',
      paint: {
        'fill-color': ['get', 'color'],
        'fill-opacity': 0.12,
      },
    });

    map.addSource('collateral-lines', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: lineFeatures },
    });
    map.addLayer({
      id: 'collateral-lines',
      type: 'line',
      source: 'collateral-lines',
      paint: {
        'line-color': ['get', 'color'],
        'line-width': 2,
        'line-opacity': 0.75,
        'line-dasharray': [2, 2],
      },
    });

    if (!hasBound) {
      map.setCenter(DEFAULT_CENTER_LNGLAT);
      map.setZoom(DEFAULT_ZOOM);
    } else if ((data.markers || []).length === 1) {
      map.flyTo({ center: [data.markers[0].lon, data.markers[0].lat], zoom: 17 });
    } else {
      map.fitBounds(bounds, { padding: 48, maxZoom: 18 });
    }
  }

  function addGebetaStyleControl(map, entry) {
    var styles = provider().styles || {};
    var wrap = document.createElement('div');
    wrap.className = 'maplibregl-ctrl maplibregl-ctrl-group collateral-gebeta-style-ctrl';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.title = 'Map style';
    btn.setAttribute('aria-label', 'Map style');
    btn.textContent = '◎';
    var menu = document.createElement('div');
    menu.className = 'collateral-gebeta-style-menu';
    menu.hidden = true;
    [
      { key: 'standard', label: 'Standard', url: styles.standard },
      { key: 'satellite', label: 'Satellite', url: styles.satellite },
      { key: 'terrain', label: 'Terrain', url: styles.terrain },
    ].forEach(function (opt) {
      if (!opt.url) return;
      var item = document.createElement('button');
      item.type = 'button';
      item.textContent = opt.label;
      item.addEventListener('click', function () {
        entry.styleKey = opt.key;
        menu.hidden = true;
        var data = entry.data;
        map.setStyle(opt.url);
        map.once('style.load', function () {
          drawGebetaMarkers(entry, data || { markers: [] });
        });
      });
      menu.appendChild(item);
    });
    btn.addEventListener('click', function () {
      menu.hidden = !menu.hidden;
    });
    wrap.appendChild(btn);
    wrap.appendChild(menu);
    map.getContainer().appendChild(wrap);
  }

  function addGebetaBadge(container) {
    var badge = document.createElement('div');
    badge.className = 'collateral-map-provider-badge';
    var docs = provider().docsUrl || 'https://docs.gebeta.app/docs';
    badge.innerHTML = 'Map: <a href="' + docs + '" target="_blank" rel="noopener">Gebeta Maps</a>';
    container.appendChild(badge);
  }

  function initGebeta(container, data, mapKey) {
    var styles = provider().styles || {};
    var styleUrl = styles.standard || 'https://tiles.gebeta.app/styles/standard/style.json';
    var map = new maplibregl.Map({
      container: container,
      style: styleUrl,
      center: DEFAULT_CENTER_LNGLAT,
      zoom: DEFAULT_ZOOM,
      attributionControl: true,
      transformRequest: gebetaTransformRequest,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    var entry = {
      engine: 'gebeta',
      map: map,
      data: data,
      domMarkers: [],
      styleKey: 'standard',
    };
    maps[mapKey] = entry;
    addGebetaStyleControl(map, entry);
    addGebetaBadge(container);
    map.on('load', function () {
      drawGebetaMarkers(entry, data || { markers: [] });
      setTimeout(function () { map.resize(); }, 200);
    });
    return entry;
  }

  /* ---------- Public API ---------- */

  function init(container, data, mapKey) {
    if (!container) return null;
    mapKey = mapKey || container.id || 'default';
    if (maps[mapKey]) {
      maps[mapKey].data = data;
      if (maps[mapKey].engine === 'gebeta') {
        if (maps[mapKey].map.isStyleLoaded()) drawGebetaMarkers(maps[mapKey], data);
        else maps[mapKey].map.once('load', function () { drawGebetaMarkers(maps[mapKey], data); });
      } else {
        drawLeafletMarkers(maps[mapKey].map, maps[mapKey].layer, data);
      }
      return maps[mapKey];
    }
    if (useGebeta()) return initGebeta(container, data, mapKey);
    if (global.L) return initLeaflet(container, data, mapKey);
    return null;
  }

  function readConfig(container) {
    var scriptId = container.getAttribute('data-config-id');
    if (!scriptId) return { markers: [] };
    var el = document.getElementById(scriptId);
    if (!el || !el.textContent) return { markers: [] };
    try { return JSON.parse(el.textContent); }
    catch (e) { return { markers: [] }; }
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
    if (entry.engine === 'gebeta') drawGebetaMarkers(entry, data);
    else drawLeafletMarkers(entry.map, entry.layer, data);
  }

  function boot() {
    document.querySelectorAll('.collateral-map-canvas').forEach(function (canvas) {
      var data = readConfig(canvas);
      init(canvas, data, canvas.id);
    });
  }

  global.CollateralMap = {
    init: init,
    updateLiveSite: updateLiveSite,
    boot: boot,
    usingGebeta: useGebeta,
  };

  document.addEventListener('DOMContentLoaded', boot);
  document.addEventListener('collateral:site-gps-updated', function (ev) {
    var d = ev.detail || {};
    if (d.mapId) updateLiveSite(d.mapId, d.lat, d.lon, d.accuracy, d.label);
  });
})(window);
