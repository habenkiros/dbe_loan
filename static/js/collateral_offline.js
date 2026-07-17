/**
 * Collateral offline PWA: register SW, queue field actions offline, sync when online.
 */
(function () {
  'use strict';

  var cfg = window.COLLATERAL_OFFLINE || {};
  var csrfToken = cfg.csrfToken || '';
  var syncUrl = cfg.syncUrl || '/collateral/offline/sync/';
  var bundleUrlTpl = cfg.bundleUrlTpl || '/collateral/offline/bundle/{id}/';
  var swUrl = cfg.swUrl || '/collateral/sw.js';

  function $(id) { return document.getElementById(id); }

  function setStatus(text, kind) {
    var el = $('offline-status-text');
    var banner = $('offline-status-banner');
    if (el) el.textContent = text;
    if (banner) {
      banner.classList.remove('offline-online', 'offline-offline', 'offline-syncing');
      banner.classList.add(kind || 'offline-online');
    }
  }

  function updatePendingBadge() {
    if (!window.CollateralOfflineDB) return;
    CollateralOfflineDB.pendingCount().then(function (n) {
      var badge = $('offline-pending-count');
      if (badge) {
        badge.textContent = String(n);
        badge.hidden = n === 0;
      }
      var syncBtn = $('offline-sync-btn');
      if (syncBtn) syncBtn.disabled = n === 0 || !navigator.onLine;
    });
  }

  function refreshOnlineUi() {
    if (navigator.onLine) {
      setStatus('Online — field data syncs to the server.', 'offline-online');
    } else {
      setStatus('Offline — captures are saved on this device until you sync.', 'offline-offline');
    }
    updatePendingBadge();
  }

  function getCsrf() {
    if (csrfToken) return csrfToken;
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function formToObject(form) {
    var fd = new FormData(form);
    var obj = {};
    fd.forEach(function (value, key) {
      if (value instanceof File) return;
      obj[key] = value;
    });
    return obj;
  }

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        var result = reader.result || '';
        var base64 = String(result).split(',')[1] || '';
        resolve({
          name: file.name || 'photo.jpg',
          type: file.type || 'image/jpeg',
          size: file.size,
          data_base64: base64,
        });
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function detectVisitContext() {
    var wrap = document.querySelector('.field-visit-wrap');
    if (!wrap) return null;
    return {
      loan_request_id: Number(cfg.loanRequestId || 0) || null,
      visit_kind: cfg.visitKind || '',
      subject_id: Number(cfg.subjectId || 0) || null,
      subject_type: cfg.subjectType || '',
    };
  }

  function queueForm(form, kind) {
    var ctx = detectVisitContext();
    if (!ctx || !ctx.loan_request_id) {
      alert('Cannot queue offline: missing loan context. Open field visit while online first.');
      return Promise.reject(new Error('no context'));
    }
    var payload = formToObject(form);
    var item = {
      kind: kind,
      loan_request_id: ctx.loan_request_id,
      visit_kind: ctx.visit_kind,
      subject_id: ctx.subject_id,
      subject_type: ctx.subject_type,
      fields: payload,
      client_url: window.location.pathname,
    };

    var fileInput = form.querySelector('input[type="file"][name="image"]');
    var file = fileInput && fileInput.files && fileInput.files[0];
    var chain = Promise.resolve();
    if (file) {
      chain = fileToBase64(file).then(function (blobMeta) {
        item.image = blobMeta;
      });
    }
    return chain.then(function () {
      return CollateralOfflineDB.enqueue(item);
    }).then(function () {
      updatePendingBadge();
      setStatus('Saved offline. Sync when you have connection.', 'offline-offline');
      alert('Saved on this device (offline). It will upload when you tap Sync or reconnect.');
    });
  }

  function bindOfflineForms() {
    if (!window.CollateralOfflineDB) return;
    var forms = [
      { id: 'field-step1-form', kind: 'building_site' },
      { id: 'asset-step1-form', kind: 'asset_site' },
      { id: 'field-photo-form', kind: 'photo' },
      { id: 'boq-form', kind: 'boq' },
    ];
    forms.forEach(function (spec) {
      var form = $(spec.id);
      if (!form || form._offlineBound) return;
      form._offlineBound = true;
      form.addEventListener('submit', function (ev) {
        if (navigator.onLine) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        queueForm(form, spec.kind).catch(function () {});
      }, true);
    });
  }

  function syncOne(item) {
    var body = {
      id: item.id,
      kind: item.kind,
      loan_request_id: item.loan_request_id,
      visit_kind: item.visit_kind,
      subject_id: item.subject_id,
      subject_type: item.subject_type,
      fields: item.fields || {},
      image: item.image || null,
    };
    return fetch(syncUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
      },
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || ('Sync failed (' + res.status + ')'));
        }
        return data;
      });
    });
  }

  function runSync() {
    if (!navigator.onLine) {
      alert('You are offline. Connect to the network, then sync.');
      return;
    }
    if (!window.CollateralOfflineDB) return;
    setStatus('Syncing pending field captures…', 'offline-syncing');
    var syncBtn = $('offline-sync-btn');
    if (syncBtn) syncBtn.disabled = true;

    CollateralOfflineDB.listPending().then(function (rows) {
      var chain = Promise.resolve();
      var ok = 0;
      var fail = 0;
      rows.forEach(function (row) {
        chain = chain.then(function () {
          return syncOne(row).then(function () {
            ok += 1;
            return CollateralOfflineDB.markDone(row.id);
          }).catch(function (err) {
            fail += 1;
            return CollateralOfflineDB.markFailed(row.id, err.message || err);
          });
        });
      });
      return chain.then(function () {
        updatePendingBadge();
        if (fail === 0) {
          setStatus('Synced ' + ok + ' item(s). Online.', 'offline-online');
          if (ok > 0) {
            alert('Synced ' + ok + ' offline item(s). Reloading…');
            window.location.reload();
          }
        } else {
          setStatus('Synced ' + ok + ', failed ' + fail + '. Check and retry.', 'offline-offline');
          alert('Synced ' + ok + ', failed ' + fail + '. Failed items stay in the queue.');
        }
      });
    }).finally(function () {
      refreshOnlineUi();
    });
  }

  function prefetchBundle() {
    var loanId = cfg.loanRequestId;
    if (!loanId || !navigator.onLine || !window.CollateralOfflineDB) return;
    var url = bundleUrlTpl.replace('{id}', String(loanId));
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          return CollateralOfflineDB.saveBundle(data.bundle);
        }
      })
      .catch(function () { /* ignore prefetch errors */ });
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register(swUrl, { scope: '/collateral/' }).then(function (reg) {
      if (reg.waiting) {
        reg.waiting.postMessage({ type: 'SKIP_WAITING' });
      }
    }).catch(function () { /* SW optional on http non-localhost */ });
  }

  function bindUi() {
    var syncBtn = $('offline-sync-btn');
    if (syncBtn) syncBtn.addEventListener('click', runSync);
    var prepBtn = $('offline-prep-btn');
    if (prepBtn) {
      prepBtn.addEventListener('click', function () {
        if (!navigator.onLine) {
          alert('Connect online first to prepare this loan for offline use.');
          return;
        }
        prefetchBundle();
        alert('Loan data cached for offline field visit on this device.');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('offline-status-banner')) return;
    registerServiceWorker();
    bindUi();
    bindOfflineForms();
    refreshOnlineUi();
    prefetchBundle();
    window.addEventListener('online', function () {
      refreshOnlineUi();
      runSync();
    });
    window.addEventListener('offline', refreshOnlineUi);
  });
})();
