/**
 * Collateral field visit: GPS capture, webcam (laptop), and mobile camera uploads.
 */
(function () {
  'use strict';

  function byId(id) {
    return document.getElementById(id);
  }

  function isMobile() {
    return preferNativeCamera();
  }

  function preferNativeCamera() {
    var ua = navigator.userAgent || '';
    if (/Android|iPhone|iPad|iPod|Mobile|Tablet|Silk|Kindle/i.test(ua)) return true;
    // iPadOS 13+ can report as desktop Safari
    if (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1) return true;
    if ((navigator.maxTouchPoints || 0) > 1) return true;
    try {
      if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) return true;
    } catch (e) { /* ignore */ }
    return false;
  }

  function openFilePicker(input, mode) {
    if (!input) return;
    input.setAttribute('accept', 'image/*');
    if (mode === 'camera') {
      input.setAttribute('capture', 'environment');
    } else {
      input.removeAttribute('capture');
    }
    // Reset value so selecting the same file again still fires change
    try { input.value = ''; } catch (e) { /* ignore */ }
    input.click();
  }

  function geoBlockedReason() {
    if (!window.isSecureContext) {
      return (
        'Location and camera need a secure page. Use https:// or open via ' +
        'http://localhost:8000 (not http://192.168.x.x).'
      );
    }
    if (!navigator.geolocation) {
      return 'GPS is not supported in this browser.';
    }
    return null;
  }

  function geoErrorText(err) {
    if (!err) return 'Location unavailable';
    if (err.code === 1) return 'Location permission denied — allow location for this site in browser settings';
    if (err.code === 2) return 'Location unavailable — check OS location services (Wi‑Fi/GPS)';
    if (err.code === 3) return 'Location timed out — try again near a window or enable Wi‑Fi';
    return 'GPS error: ' + (err.message || 'unknown');
  }

  function setHidden(prefix, lat, lon, accuracy) {
    var latEl = byId(prefix ? prefix + '_gps_lat' : 'gps_lat');
    var lonEl = byId(prefix ? prefix + '_gps_lon' : 'gps_lon');
    var accEl = byId(prefix ? prefix + '_gps_accuracy_m' : 'gps_accuracy_m');
    if (latEl) latEl.value = lat != null ? String(lat) : '';
    if (lonEl) lonEl.value = lon != null ? String(lon) : '';
    if (accEl) accEl.value = accuracy != null ? String(accuracy) : '';
  }

  function readHidden(prefix) {
    var latEl = byId(prefix ? prefix + '_gps_lat' : 'gps_lat');
    var lonEl = byId(prefix ? prefix + '_gps_lon' : 'gps_lon');
    var accEl = byId(prefix ? prefix + '_gps_accuracy_m' : 'gps_accuracy_m');
    return {
      lat: latEl && latEl.value ? parseFloat(latEl.value) : null,
      lon: lonEl && lonEl.value ? parseFloat(lonEl.value) : null,
      accuracy: accEl && accEl.value ? parseFloat(accEl.value) : null,
    };
  }

  function updateGpsStatus(el, lat, lon, accuracy, label) {
    if (!el) return;
    el.classList.remove('field-gps-ok', 'field-gps-warn', 'field-gps-none');
    if (lat == null || lon == null || isNaN(lat) || isNaN(lon)) {
      el.classList.add('field-gps-none');
      el.textContent = label || 'GPS not captured yet.';
      if (el.id === 'site-gps-status') toggleAttestation('site', null, accuracy);
      if (el.id === 'photo-gps-status') toggleAttestation('photo', null, accuracy);
      return;
    }
    var text = (label || 'Location') + ': ' + Number(lat).toFixed(6) + ', ' + Number(lon).toFixed(6);
    if (accuracy != null && !isNaN(accuracy)) {
      text += ' (±' + Math.round(accuracy) + ' m)';
    }
    el.textContent = text;
    var threshold = window.COLLATERAL_GPS_WEAK_M || 100;
    if (accuracy == null || isNaN(accuracy) || accuracy > threshold) {
      el.classList.add('field-gps-warn');
    } else {
      el.classList.add('field-gps-ok');
    }
    if (el.id === 'site-gps-status') toggleAttestation('site', lat, accuracy);
    if (el.id === 'photo-gps-status') toggleAttestation('photo', lat, accuracy);
  }

  function toggleAttestation(kind, lat, accuracy) {
    var threshold = window.COLLATERAL_GPS_WEAK_M || 100;
    var weak = lat == null || accuracy == null || isNaN(accuracy) || accuracy > threshold;
    var panel = byId(kind === 'site' ? 'site-gps-attestation' : 'photo-gps-attestation');
    if (!panel) return;
    panel.hidden = !weak;
  }

  function applyGpsReading(prefix, statusEl, lat, lon, accuracy, label) {
    setHidden(prefix, lat, lon, accuracy);
    updateGpsStatus(statusEl, lat, lon, accuracy, label);
    if (prefix === 'site' && window.COLLATERAL_SITE_MAP_ID && window.CollateralMap) {
      window.CollateralMap.updateLiveSite(
        window.COLLATERAL_SITE_MAP_ID,
        lat,
        lon,
        accuracy,
        label || 'Registered site'
      );
    }
  }

  function captureGpsPromise(prefix, statusEl, btn) {
    var blocked = geoBlockedReason();
    if (blocked) {
      updateGpsStatus(statusEl, null, null, null, blocked);
      return Promise.reject(new Error(blocked));
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Getting location…';
    }
    return new Promise(function (resolve, reject) {
      var best = null;
      var samples = 0;
      var settled = false;
      var watchId = null;

      function finish(pos, err) {
        if (settled) return;
        settled = true;
        if (watchId != null && navigator.geolocation.clearWatch) {
          navigator.geolocation.clearWatch(watchId);
        }
        if (btn) {
          btn.disabled = false;
          btn.textContent = pos ? 'Refresh location' : 'Try again';
        }
        if (pos) {
          var c = pos.coords;
          applyGpsReading(prefix, statusEl, c.latitude, c.longitude, c.accuracy, 'Captured');
          resolve(pos);
        } else {
          var msg = geoErrorText(err);
          updateGpsStatus(statusEl, null, null, null, msg);
          reject(err || new Error(msg));
        }
      }

      function onPosition(pos) {
        samples += 1;
        if (!best || pos.coords.accuracy < best.coords.accuracy) {
          best = pos;
          applyGpsReading(
            prefix,
            statusEl,
            pos.coords.latitude,
            pos.coords.longitude,
            pos.coords.accuracy,
            'Capturing…'
          );
        }
        var targetAccuracy = 35;
        if (best && (best.coords.accuracy <= targetAccuracy || samples >= 6)) {
          finish(best, null);
        }
      }

      if (navigator.geolocation.watchPosition) {
        watchId = navigator.geolocation.watchPosition(
          onPosition,
          function (err) { finish(null, err); },
          { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 }
        );
        setTimeout(function () {
          if (!settled) {
            if (best) {
              finish(best, null);
            } else {
              finish(null, { code: 3, message: 'Location timed out' });
            }
          }
        }, 28000);
      } else {
        navigator.geolocation.getCurrentPosition(
          function (pos) { finish(pos, null); },
          function (err) { finish(null, err); },
          { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 }
        );
      }
    });
  }

  function captureGps(prefix, statusEl, btn) {
    captureGpsPromise(prefix, statusEl, btn).catch(function () {});
  }

  function compressImage(file, maxWidth, quality, callback) {
    if (!file || !file.type || file.type.indexOf('image/') !== 0) {
      callback(file);
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      var img = new Image();
      img.onload = function () {
        var w = img.width;
        var h = img.height;
        if (w > maxWidth) {
          h = Math.round(h * (maxWidth / w));
          w = maxWidth;
        }
        var canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        canvas.toBlob(
          function (blob) {
            callback(blob ? new File([blob], file.name || 'photo.jpg', { type: 'image/jpeg' }) : file);
          },
          'image/jpeg',
          quality || 0.82
        );
      };
      img.onerror = function () { callback(file); };
      img.src = e.target.result;
    };
    reader.onerror = function () { callback(file); };
    reader.readAsDataURL(file);
  }

  function setFileOnInput(input, file, callback) {
    compressImage(file, 1600, 0.82, function (compressed) {
      try {
        var dt = new DataTransfer();
        dt.items.add(compressed);
        input.files = dt.files;
      } catch (e) {
        /* keep original selection */
      }
      if (callback) callback(compressed);
    });
  }

  function bindSubmitWithGps(form, prefix, statusEl, opts) {
    if (!form) return;
    opts = opts || {};
    form.addEventListener('submit', function (ev) {
      if (form._collateralAllowSubmit) {
        form._collateralAllowSubmit = false;
        return;
      }
      var coords = readHidden(prefix);
      if (coords.lat != null && coords.lon != null) return;

      if (opts.optional) return;

      var blocked = geoBlockedReason();
      if (blocked) {
        if (opts.optional) return;
        ev.preventDefault();
        updateGpsStatus(statusEl, null, null, null, blocked);
        return;
      }

      ev.preventDefault();
      var submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = opts.waitLabel || 'Getting location…';
      }

      captureGpsPromise(prefix, statusEl, null)
        .catch(function () { /* still submit — attestation can cover weak GPS */ })
        .finally(function () {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = opts.submitLabel || 'Save';
          }
          form._collateralAllowSubmit = true;
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.submit();
          }
        });
    });
  }

  function initSecureContextBanner() {
    var banner = byId('field-secure-context-banner');
    if (!banner) return;
    if (!window.isSecureContext) {
      banner.hidden = false;
    }
  }

  function initLiveSitePreview() {
    var liveMap = document.querySelector('.collateral-map-canvas[data-live-site="1"]');
    if (!liveMap || !window.CollateralMap) return;
    if (liveMap.getAttribute('data-auto-live-gps') === '0') return;
    var status = byId('site-gps-status');
    var saved = readHidden('site');
    if (saved.lat != null && saved.lon != null) {
      applyGpsReading('site', status, saved.lat, saved.lon, saved.accuracy, 'Saved site');
    }
  }

  function initSiteGps() {
    var btn = byId('btn-mark-site-gps');
    var status = byId('site-gps-status');
    var form = byId('field-step1-form') || byId('asset-step1-form');
    var saved = readHidden('site');
    if (status && saved.lat != null && saved.lon != null) {
      applyGpsReading('site', status, saved.lat, saved.lon, saved.accuracy, 'Saved site');
    } else {
      initLiveSitePreview();
    }
    if (btn) {
      btn.addEventListener('click', function () {
        captureGps('site', status, btn);
      });
    }
    bindSubmitWithGps(form, 'site', status, {
      optional: true,
      waitLabel: 'Getting location…',
      submitLabel: 'Save',
    });
  }

  function initPhotoCapture() {
    var form = byId('field-photo-form');
    var input = byId('field-photo-input');
    var status = byId('photo-gps-status');
    var btn = byId('btn-capture-photo-gps');
    var takeBtn = byId('btn-take-photo');
    var galleryBtn = byId('btn-pick-gallery');
    if (!form || !input) return;

    var native = preferNativeCamera();
    input.setAttribute('accept', 'image/*');
    if (native) {
      input.setAttribute('capture', 'environment');
    } else {
      input.removeAttribute('capture');
    }

    function refreshPhotoGps() {
      captureGps('', status, btn);
    }
    if (btn) {
      btn.addEventListener('click', refreshPhotoGps);
    }

    if (takeBtn) {
      takeBtn.addEventListener('click', function () {
        openFilePicker(input, 'camera');
      });
    }
    if (galleryBtn) {
      galleryBtn.addEventListener('click', function () {
        openFilePicker(input, 'gallery');
      });
    }

    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var coords = readHidden('');
      if (coords.lat == null) {
        refreshPhotoGps();
      }
      setFileOnInput(input, file);
    });

    bindSubmitWithGps(form, '', status, {
      optional: true,
      waitLabel: 'Getting location…',
      submitLabel: 'Save photo',
    });

    initWebcam(input, status, { desktopOnly: true });
  }

  function stopStream(stream) {
    if (!stream) return;
    stream.getTracks().forEach(function (t) { t.stop(); });
  }

  function initWebcam(input, gpsStatus, opts) {
    opts = opts || {};
    var openBtn = byId('btn-webcam-open');
    var snapBtn = byId('btn-webcam-snap');
    var closeBtn = byId('btn-webcam-close');
    var panel = byId('field-webcam-panel');
    var video = byId('field-webcam-video');
    if (!openBtn || !input) return;

    var stream = null;
    var native = preferNativeCamera();

    // Phones/tablets: never use in-browser webcam stream — use rear camera / gallery buttons.
    if (opts.desktopOnly && native) {
      openBtn.hidden = true;
      openBtn.style.display = 'none';
      return;
    }
    openBtn.hidden = false;
    openBtn.style.display = '';
    openBtn.textContent = native ? 'Open phone rear camera' : 'Use laptop webcam';

    function closePanel() {
      stopStream(stream);
      stream = null;
      if (panel) panel.hidden = true;
      if (video) video.srcObject = null;
    }

    openBtn.addEventListener('click', function () {
      if (preferNativeCamera()) {
        openFilePicker(input, 'camera');
        return;
      }
      if (!window.isSecureContext) {
        alert(geoBlockedReason());
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Webcam is not supported in this browser. Use “Choose from gallery” instead.');
        return;
      }
      openBtn.disabled = true;
      openBtn.textContent = 'Opening camera…';
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      }).then(function (s) {
        stream = s;
        if (video) {
          video.srcObject = s;
          video.play();
        }
        if (panel) panel.hidden = false;
        openBtn.disabled = false;
        openBtn.textContent = 'Use laptop webcam';
      }).catch(function (err) {
        return navigator.mediaDevices.getUserMedia({ video: true, audio: false }).then(function (s) {
          stream = s;
          if (video) {
            video.srcObject = s;
            video.play();
          }
          if (panel) panel.hidden = false;
          openBtn.disabled = false;
          openBtn.textContent = 'Use laptop webcam';
        }).catch(function (err2) {
          openBtn.disabled = false;
          openBtn.textContent = 'Use laptop webcam';
          alert('Could not open camera: ' + ((err2 && err2.message) || err.message || err.name) + '. Allow camera access for this site.');
        });
      });
    });

    if (closeBtn) {
      closeBtn.addEventListener('click', closePanel);
    }

    if (snapBtn) {
      snapBtn.addEventListener('click', function () {
        if (!video || !video.videoWidth) return;
        var canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        canvas.toBlob(function (blob) {
          if (!blob) return;
          var file = new File([blob], 'webcam-' + Date.now() + '.jpg', { type: 'image/jpeg' });
          setFileOnInput(input, file, function () {
            var coords = readHidden('');
            if (coords.lat == null) {
              captureGps('', gpsStatus, null);
            }
            closePanel();
          });
        }, 'image/jpeg', 0.88);
      });
    }
  }

  function initBuildingImagesPage() {
    var form = byId('upload-form');
    var input = byId('id_image');
    if (!form || !input) return;
    if (isMobile()) {
      input.setAttribute('capture', 'environment');
    }
    input.setAttribute('accept', 'image/*');

    var latHidden = byId('gps_lat');
    if (!latHidden) {
      latHidden = document.createElement('input');
      latHidden.type = 'hidden';
      latHidden.name = 'gps_lat';
      latHidden.id = 'gps_lat';
      form.appendChild(latHidden);
      var lonHidden = document.createElement('input');
      lonHidden.type = 'hidden';
      lonHidden.name = 'gps_lon';
      lonHidden.id = 'gps_lon';
      form.appendChild(lonHidden);
      var accHidden = document.createElement('input');
      accHidden.type = 'hidden';
      accHidden.name = 'gps_accuracy_m';
      accHidden.id = 'gps_accuracy_m';
      form.appendChild(accHidden);
    }

    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) return;
      if (readHidden('').lat == null) {
        captureGps('', null, null);
      }
      setFileOnInput(input, file);
    });

    bindSubmitWithGps(form, '', null, { optional: true, submitLabel: 'Upload' });
    initWebcam(input, null, { desktopOnly: true });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSecureContextBanner();
    initSiteGps();
    initPhotoCapture();
    initBuildingImagesPage();
  });
})();
