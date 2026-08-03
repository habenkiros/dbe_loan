/**
 * Collateral offline PWA: queue field actions offline, sync with production retries.
 */
(function () {
  'use strict';

  var cfg = window.COLLATERAL_OFFLINE || {};
  var csrfToken = cfg.csrfToken || '';
  var syncUrl = cfg.syncUrl || '/collateral/offline/sync/';
  var pingUrl = cfg.pingUrl || '/collateral/offline/ping/';
  var bundleUrlTpl = cfg.bundleUrlTpl || '/collateral/offline/bundle/{id}/';
  var swUrl = cfg.swUrl || '/collateral/sw.js';
  var SYNC_TIMEOUT_MS = 30000;
  var AUTO_RETRY_INTERVAL_MS = 5000;
  var SYNC_CONCURRENCY = 3;
  var REACHABLE_TTL_MS = 8000;
  var syncInFlight = false;
  var syncAgainOpts = null;
  var autoRetryTimer = null;
  var lastReachableAt = 0;
  var lastReachable = false;

  function $(id) { return document.getElementById(id); }

  function setStatus(text, kind) {
    var el = $('offline-status-text');
    var banner = $('offline-status-banner');
    if (el) el.textContent = text;
    if (banner) {
      banner.classList.remove('offline-online', 'offline-offline', 'offline-syncing', 'offline-warn');
      banner.classList.add(kind || 'offline-online');
    }
  }

  function updatePendingBadge() {
    if (!window.CollateralOfflineDB) return;
    CollateralOfflineDB.queueStats().then(function (stats) {
      var active = (stats.pending || 0) + (stats.failed || 0);
      var badge = $('offline-pending-count');
      if (badge) {
        badge.textContent = String(active);
        badge.hidden = active === 0;
      }
      var abandonedBadge = $('offline-abandoned-count');
      if (abandonedBadge) {
        abandonedBadge.textContent = String(stats.abandoned || 0);
        abandonedBadge.hidden = !stats.abandoned;
      }
      var syncBtn = $('offline-sync-btn');
      if (syncBtn) syncBtn.disabled = (active === 0 && !(stats.abandoned)) || !navigator.onLine;
      var retryAbandonedBtn = $('offline-retry-abandoned-btn');
      if (retryAbandonedBtn) {
        retryAbandonedBtn.hidden = !stats.abandoned;
        retryAbandonedBtn.disabled = !navigator.onLine || !stats.abandoned;
      }
    });
  }

  function refreshOnlineUi() {
    var apply = function (reachable) {
      if (!window.CollateralOfflineDB) {
        if (reachable) {
          setStatus('Online — field data syncs to the server.', 'offline-online');
        } else {
          setStatus('Offline — captures are saved on this device until you sync.', 'offline-offline');
        }
        return;
      }
      CollateralOfflineDB.queueStats().then(function (stats) {
        var active = (stats.pending || 0) + (stats.failed || 0);
        if (!reachable) {
          setStatus(
            active
              ? ('Offline — ' + active + ' capture(s) saved on this device.')
              : 'Offline — captures are saved on this device until you sync.',
            'offline-offline'
          );
        } else if (stats.abandoned) {
          setStatus(
            'Online — ' + stats.abandoned + ' item(s) need manual retry after max attempts.',
            'offline-warn'
          );
        } else if (active) {
          setStatus(
            'Online — ' + active + ' item(s) waiting to sync (auto-retry on).',
            'offline-online'
          );
        } else {
          setStatus('Online — field data syncs to the server.', 'offline-online');
        }
        updatePendingBadge();
      });
    };
    if (!navigator.onLine) {
      apply(false);
      return;
    }
    serverReachable().then(apply);
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

  function probeTimeoutSignal(ms) {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
      try { return AbortSignal.timeout(ms); } catch (e) { /* fall through */ }
    }
    if (typeof AbortController === 'undefined') return undefined;
    var controller = new AbortController();
    setTimeout(function () {
      try { controller.abort(); } catch (e) { /* ignore */ }
    }, ms);
    return controller.signal;
  }

  /**
   * navigator.onLine is true on cellular even when the PC LAN IP is dead.
   * Probe the dedicated ping endpoint (SW does not cache it).
   */
  function serverReachable(force) {
    if (!force && lastReachableAt && (Date.now() - lastReachableAt) < REACHABLE_TTL_MS) {
      return Promise.resolve(lastReachable);
    }
    return fetch(pingUrl, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      signal: probeTimeoutSignal(2000),
    }).then(function (res) {
      lastReachable = !!(res && res.ok);
      lastReachableAt = Date.now();
      return lastReachable;
    }).catch(function () {
      lastReachable = false;
      lastReachableAt = Date.now();
      return false;
    });
  }

  function newClientUid() {
    return 'off-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function shouldQueueLocally() {
    if (!navigator.onLine) return Promise.resolve(true);
    return serverReachable().then(function (ok) { return !ok; });
  }

  /** After offline save_next, open the next cached field-visit step. */
  function nextFieldVisitStepUrl() {
    var path = (window.location.pathname || '').replace(/\/+$/, '') || '/';
    var match = path.match(/^(.*\/field-visit)(?:\/(\d+))?$/);
    if (!match) return null;
    var base = match[1];
    var cur = match[2] ? parseInt(match[2], 10) : 1;
    if (!cur || cur < 1) cur = 1;
    return base + '/' + (cur + 1) + '/';
  }

  function afterOfflineQueue(form, fields) {
    var action = (fields && fields.action) || '';
    var next = action === 'save_next' ? nextFieldVisitStepUrl() : null;
    updatePendingBadge();
    setStatus('Saved offline. Will auto-sync when connection returns.', 'offline-offline');
    if (next) {
      alert('Saved on this device. Opening next step…\nIt will upload when you reconnect or tap Sync now.');
      window.location.href = next;
      return;
    }
    alert('Saved on this device (offline). It will upload when you reconnect or tap Sync now.');
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
      client_uid: newClientUid(),
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
      afterOfflineQueue(form, payload);
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
        if (form._offlineNativePass) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        shouldQueueLocally().then(function (useOffline) {
          if (!useOffline) {
            form._offlineNativePass = true;
            // Native submit bypasses this listener and hits Django.
            HTMLFormElement.prototype.submit.call(form);
            return;
          }
          return queueForm(form, spec.kind);
        }).catch(function (err) {
          // Only fall back to queue on reachability/network failures — never re-queue after enqueue.
          if (err && err.message === 'no context') return;
          setStatus('Could not save offline: ' + ((err && err.message) || 'unknown'), 'offline-warn');
        });
      }, true);
    });
  }

  function SyncError(message, permanent, status) {
    var err = new Error(message);
    err.permanent = !!permanent;
    err.status = status || 0;
    return err;
  }

  function syncOne(item) {
    var body = {
      id: item.id,
      client_uid: item.client_uid || ('id-' + item.id),
      kind: item.kind,
      loan_request_id: item.loan_request_id,
      visit_kind: item.visit_kind,
      subject_id: item.subject_id,
      subject_type: item.subject_type,
      fields: item.fields || {},
      image: item.image || null,
    };
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = null;
    if (controller) {
      timer = setTimeout(function () {
        try { controller.abort(); } catch (e) { /* ignore */ }
      }, SYNC_TIMEOUT_MS);
    }
    return fetch(syncUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
      },
      body: JSON.stringify(body),
      signal: controller ? controller.signal : undefined,
    }).then(function (res) {
      lastReachable = true;
      lastReachableAt = Date.now();
      return res.json().then(function (data) {
        if (!res.ok || !data.ok) {
          var permanent = !!(data && data.permanent) || res.status === 400 || res.status === 403;
          throw SyncError(
            (data && data.error) || ('Sync failed (' + res.status + ')'),
            permanent,
            res.status
          );
        }
        return data;
      }, function () {
        throw SyncError('Sync failed (' + res.status + ') — invalid response', res.status === 400 || res.status === 403, res.status);
      });
    }).catch(function (err) {
      if (err && err.name === 'AbortError') {
        throw SyncError('Sync timed out after ' + Math.round(SYNC_TIMEOUT_MS / 1000) + 's', false, 0);
      }
      if (err && err.permanent != null) throw err;
      if (err && err.message) throw SyncError(err.message, false, 0);
      throw SyncError('Network error during sync', false, 0);
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  function mapPool(items, limit, worker) {
    var idx = 0;
    var active = 0;
    var results = [];
    return new Promise(function (resolve) {
      function next() {
        if (idx >= items.length && active === 0) {
          resolve(results);
          return;
        }
        while (active < limit && idx < items.length) {
          (function (i) {
            active += 1;
            Promise.resolve(worker(items[i], i)).then(function (r) {
              results[i] = r;
            }).catch(function (err) {
              results[i] = { error: err };
            }).then(function () {
              active -= 1;
              next();
            });
          })(idx);
          idx += 1;
        }
      }
      next();
    });
  }

  function runSync(opts) {
    opts = opts || {};
    if (!navigator.onLine) {
      if (!opts.silent) alert('You are offline. Connect to the network, then sync.');
      return Promise.resolve();
    }
    if (!window.CollateralOfflineDB) return Promise.resolve();
    if (syncInFlight) {
      // Don't drop manual Sync now while auto-retry is running.
      if (opts.force || !syncAgainOpts) syncAgainOpts = opts;
      return Promise.resolve();
    }

    return serverReachable(!!opts.force).then(function (reachable) {
      if (!reachable) {
        if (!opts.silent) {
          alert('Server unreachable (PC Wi‑Fi/hotspot). Reconnect, then sync.');
          refreshOnlineUi();
        }
        return;
      }
      return runSyncBody(opts);
    });
  }

  function processRow(row, doneCount, total) {
    setStatus('Syncing ' + doneCount + '/' + total + '…', 'offline-syncing');
    return syncOne(row).then(function () {
      return CollateralOfflineDB.markDone(row.id).then(function () {
        return { ok: 1, fail: 0, abandoned: 0 };
      });
    }).catch(function (err) {
      return CollateralOfflineDB.markFailed(row.id, err.message || err, {
        permanent: !!(err && err.permanent),
      }).then(function (outcome) {
        if (outcome && outcome.abandoned) return { ok: 0, fail: 0, abandoned: 1 };
        return { ok: 0, fail: 1, abandoned: 0 };
      });
    });
  }

  /**
   * @param {Object} opts
   * @param {boolean} [opts.force] - Sync now: ignore backoff, reset abandoned if requested
   * @param {boolean} [opts.silent] - background auto-retry: no alerts/reload spam
   * @param {boolean} [opts.includeAbandoned] - requeue abandoned first
   */
  function runSyncBody(opts) {
    opts = opts || {};
    syncInFlight = true;

    setStatus('Syncing pending field captures…', 'offline-syncing');
    var syncBtn = $('offline-sync-btn');
    if (syncBtn) syncBtn.disabled = true;

    var prepare = Promise.resolve();
    if (opts.force) {
      prepare = CollateralOfflineDB.listPending().then(function (rows) {
        var chain = Promise.resolve();
        rows.forEach(function (row) {
          chain = chain.then(function () {
            return CollateralOfflineDB.resetForManualRetry(row.id);
          });
        });
        return chain;
      });
      if (opts.includeAbandoned) {
        prepare = prepare.then(function () {
          return CollateralOfflineDB.resetAbandonedAll();
        });
      }
    }

    return prepare.then(function () {
      return opts.force
        ? CollateralOfflineDB.listPending()
        : CollateralOfflineDB.listReadyToSync();
    }).then(function (rows) {
      if (!rows.length) {
        if (!opts.silent) {
          CollateralOfflineDB.queueStats().then(function (stats) {
            if (stats.abandoned) {
              setStatus(
                'No items ready — ' + stats.abandoned + ' abandoned. Use Retry abandoned.',
                'offline-warn'
              );
            } else if ((stats.pending + stats.failed) > 0) {
              setStatus('Waiting for retry backoff…', 'offline-online');
            }
          });
        }
        return { ok: 0, fail: 0, abandoned: 0, empty: true };
      }

      // Site/BOQ first (sequential), then photos in parallel for speed.
      var ordered = rows.filter(function (r) {
        return r.kind === 'building_site' || r.kind === 'asset_site' || r.kind === 'boq';
      });
      var photos = rows.filter(function (r) { return r.kind === 'photo'; });
      var other = rows.filter(function (r) {
        return r.kind !== 'building_site' && r.kind !== 'asset_site' && r.kind !== 'boq' && r.kind !== 'photo';
      });
      var total = rows.length;
      var doneCount = 0;
      var summary = { ok: 0, fail: 0, abandoned: 0, empty: false };

      function accumulate(part) {
        summary.ok += part.ok || 0;
        summary.fail += part.fail || 0;
        summary.abandoned += part.abandoned || 0;
        doneCount += 1;
      }

      var chain = Promise.resolve();
      ordered.concat(other).forEach(function (row) {
        chain = chain.then(function () {
          return processRow(row, doneCount + 1, total).then(accumulate);
        });
      });

      return chain.then(function () {
        return mapPool(photos, SYNC_CONCURRENCY, function (row) {
          return processRow(row, doneCount + 1, total).then(function (part) {
            accumulate(part);
            return part;
          });
        });
      }).then(function () {
        return summary;
      });
    }).then(function (summary) {
      updatePendingBadge();
      if (!summary || summary.empty) return;

      if (summary.fail === 0 && summary.abandoned === 0) {
        setStatus('Synced ' + summary.ok + ' item(s). Online.', 'offline-online');
        if (!opts.silent && summary.ok > 0) {
          alert('Synced ' + summary.ok + ' offline item(s). Reloading…');
          window.location.reload();
        }
      } else {
        var msg = 'Synced ' + summary.ok +
          ', retrying later ' + summary.fail +
          ', need review ' + summary.abandoned + '.';
        setStatus(msg, summary.abandoned ? 'offline-warn' : 'offline-offline');
        if (!opts.silent) {
          alert(
            msg +
            ' Transient failures auto-retry quickly. Items that need review usually need a fix or Retry abandoned.'
          );
        }
      }
    }).catch(function (err) {
      setStatus('Sync error: ' + ((err && err.message) || 'unknown'), 'offline-warn');
    }).finally(function () {
      syncInFlight = false;
      var again = syncAgainOpts;
      syncAgainOpts = null;
      if (again) {
        runSync(again);
        return;
      }
      refreshOnlineUi();
    });
  }

  function startAutoRetry() {
    if (autoRetryTimer) return;
    autoRetryTimer = setInterval(function () {
      if (!navigator.onLine || syncInFlight) return;
      if (!window.CollateralOfflineDB) return;
      CollateralOfflineDB.listReadyToSync().then(function (rows) {
        if (rows && rows.length) {
          runSync({ silent: true, force: false });
        } else {
          updatePendingBadge();
        }
      });
    }, AUTO_RETRY_INTERVAL_MS);
  }

  function stopAutoRetry() {
    if (autoRetryTimer) {
      clearInterval(autoRetryTimer);
      autoRetryTimer = null;
    }
  }

  function showSwHealth(ok, detail) {
    var el = $('offline-sw-health');
    if (!el) return;
    el.hidden = false;
    if (ok) {
      el.innerHTML = '<span style="color:#155724;font-weight:600;">Service worker active</span> — offline pack can work off-network.';
    } else {
      el.innerHTML =
        '<span style="color:#b71c1c;font-weight:600;">Service worker not active on this device.</span> ' +
        (detail || '') +
        ' On phones this usually means the local CA is not installed. ' +
        '<a href="/collateral/offline/setup/">Phone offline setup</a>';
    }
  }

  function ensureServiceWorkerHealth() {
    if (!('serviceWorker' in navigator)) {
      showSwHealth(false, 'This browser does not support service workers.');
      return Promise.resolve(false);
    }
    return navigator.serviceWorker.getRegistration('/collateral/').then(function (reg) {
      if (reg && (reg.active || navigator.serviceWorker.controller)) {
        showSwHealth(true);
        return true;
      }
      return navigator.serviceWorker.register(swUrl, { scope: '/collateral/' })
        .then(function (r) {
          return navigator.serviceWorker.ready.then(function () {
            var ok = !!(navigator.serviceWorker.controller || (r && r.active));
            showSwHealth(ok, ok ? '' : 'Registered — reload this page once, then recheck.');
            return ok;
          });
        })
        .catch(function (err) {
          var msg = (err && err.message) || 'registration failed';
          showSwHealth(false, msg + '.');
          return false;
        });
    }).catch(function () {
      showSwHealth(false, 'Could not read service worker registration.');
      return false;
    });
  }

  function precacheUrls(urls) {
    if (!urls || !urls.length) return Promise.resolve({ ok: 0, failed: [], total: 0 });
    var cacheName = 'collateral-field-v9';
    return caches.open(cacheName).then(function (cache) {
      var ok = 0;
      var failed = [];
      var chain = Promise.resolve();
      urls.forEach(function (u) {
        chain = chain.then(function () {
          return fetch(u, { credentials: 'same-origin', cache: 'reload' }).then(function (res) {
            if (res && res.ok) {
              ok += 1;
              return cache.put(u, res.clone());
            }
            failed.push(u);
          }).catch(function () {
            failed.push(u);
          });
        });
      });
      return chain.then(function () {
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage({ type: 'PRECACHE_URLS', urls: urls });
        }
        return { ok: ok, failed: failed, total: urls.length };
      });
    });
  }

  function prefetchBundle() {
    var loanId = cfg.loanRequestId;
    if (!loanId || !navigator.onLine || !window.CollateralOfflineDB) {
      return Promise.resolve({ ok: false, reason: 'offline-or-missing' });
    }
    var url = bundleUrlTpl.replace('{id}', String(loanId));
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!(data && data.ok && data.bundle)) {
          return { ok: false, reason: 'bundle' };
        }
        var urls = data.bundle.precache_urls || [];
        return precacheUrls(urls).then(function (cacheResult) {
          var fieldFailed = (cacheResult.failed || []).filter(function (u) {
            return String(u).indexOf('/field-visit') !== -1;
          });
          var ready = cacheResult.ok > 0 && fieldFailed.length === 0 &&
            cacheResult.ok >= Math.ceil(cacheResult.total * 0.85);
          data.bundle.offline_ready = ready;
          data.bundle.cached_pages = cacheResult.ok;
          data.bundle.cached_total = cacheResult.total;
          data.bundle.cache_failed = (cacheResult.failed || []).slice(0, 12);
          return CollateralOfflineDB.saveBundle(data.bundle).then(function () {
            return {
              ok: ready,
              partial: !ready && cacheResult.ok > 0,
              cached_pages: cacheResult.ok,
              total: cacheResult.total,
              failed: cacheResult.failed || [],
              bundle: data.bundle,
            };
          });
        });
      })
      .catch(function () { return { ok: false, reason: 'network' }; });
  }

  function registerServiceWorker() {
    return ensureServiceWorkerHealth().then(function (ok) {
      if (!ok) return false;
      return navigator.serviceWorker.getRegistration('/collateral/').then(function (reg) {
        if (reg && reg.waiting) {
          reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
        return true;
      });
    });
  }

  function bindUi() {
    var syncBtn = $('offline-sync-btn');
    if (syncBtn) {
      syncBtn.addEventListener('click', function () {
        runSync({ force: true, silent: false });
      });
    }
    var retryAbandonedBtn = $('offline-retry-abandoned-btn');
    if (retryAbandonedBtn) {
      retryAbandonedBtn.addEventListener('click', function () {
        runSync({ force: true, silent: false, includeAbandoned: true });
      });
    }
    var prepBtn = $('offline-prep-btn');
    if (prepBtn) {
      prepBtn.addEventListener('click', function () {
        if (!navigator.onLine) {
          alert('Connect to the branch PC Wi‑Fi first to download this loan pack.');
          return;
        }
        prepBtn.disabled = true;
        prepBtn.textContent = 'Downloading…';
        ensureServiceWorkerHealth().then(function (swOk) {
          return prefetchBundle().then(function (result) {
            prepBtn.disabled = false;
            prepBtn.textContent = 'Download for offline';
            if (result && result.ok && !swOk) {
              alert(
                'Pages were cached, but the service worker is NOT active on this phone.\n\n' +
                'Without it, Airplane Mode / leaving Wi‑Fi will show “site can’t be reached.”\n\n' +
                'Fix: open Phone offline setup, install the DECSI Field CA, reopen HTTPS with a lock icon, reload, then Download again.\n\n' +
                'Cached ' + (result.cached_pages || 0) + '/' + (result.total || 0) + ' files.'
              );
              return;
            }
            if (result && result.ok) {
              alert(
                'Loan pack ready on this phone.\n\n' +
                'Cached ' + (result.cached_pages || 0) + ' of ' + (result.total || 0) + ' pages.\n\n' +
                'Next:\n' +
                '1. Install app (Add to Home Screen) if not already.\n' +
                '2. Test: Airplane Mode → open Home Screen app → open this loan.\n' +
                '3. On site: open only that installed app (do not type an IP).\n' +
                '4. Sync now when back on PC Wi‑Fi.'
              );
            } else if (result && result.partial) {
              alert(
                'Partial download: ' + (result.cached_pages || 0) + '/' + (result.total || 0) +
                '.\nStay on PC Wi‑Fi and tap Download for offline again until all field steps succeed.'
              );
            } else {
              alert('Could not download loan pack. Stay on PC Wi‑Fi, open the field visit, then try again.');
            }
          });
        });
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('offline-status-banner')) return;
    registerServiceWorker();
    bindUi();
    bindOfflineForms();
    refreshOnlineUi();
    // Do not auto-download the whole pack on every page load — that fights Sync now.
    // Pack download is explicit via "Download for offline".
    startAutoRetry();
    window.addEventListener('online', function () {
      refreshOnlineUi();
      startAutoRetry();
      runSync({ force: true, silent: true });
    });
    window.addEventListener('offline', function () {
      refreshOnlineUi();
    });
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && navigator.onLine) {
        runSync({ silent: true, force: false });
      }
    });
  });
})();
