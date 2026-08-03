/**
 * IndexedDB helpers for collateral offline field visits (production retry policy).
 */
(function (global) {
  'use strict';

  var DB_NAME = 'collateral_offline_v1';
  var DB_VERSION = 1;
  var STORE_QUEUE = 'sync_queue';
  var STORE_BUNDLES = 'loan_bundles';
  var STORE_DRAFTS = 'field_drafts';

  // Production retry policy
  var MAX_ATTEMPTS = 8;
  var BASE_BACKOFF_MS = 5000;       // 5s
  var MAX_BACKOFF_MS = 10 * 60 * 1000; // 10 min

  function openDb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (ev) {
        var db = ev.target.result;
        if (!db.objectStoreNames.contains(STORE_QUEUE)) {
          var q = db.createObjectStore(STORE_QUEUE, { keyPath: 'id', autoIncrement: true });
          q.createIndex('status', 'status', { unique: false });
          q.createIndex('loan_request_id', 'loan_request_id', { unique: false });
        }
        if (!db.objectStoreNames.contains(STORE_BUNDLES)) {
          db.createObjectStore(STORE_BUNDLES, { keyPath: 'loan_request_id' });
        }
        if (!db.objectStoreNames.contains(STORE_DRAFTS)) {
          db.createObjectStore(STORE_DRAFTS, { keyPath: 'key' });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function withStore(storeName, mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(storeName, mode);
        var store = tx.objectStore(storeName);
        var result;
        try {
          result = fn(store);
        } catch (e) {
          reject(e);
          return;
        }
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function backoffMs(attempts) {
    // attempts is post-increment count (1..MAX)
    var exp = Math.max(0, (attempts || 1) - 1);
    var ms = BASE_BACKOFF_MS * Math.pow(2, exp);
    if (ms > MAX_BACKOFF_MS) ms = MAX_BACKOFF_MS;
    // small jitter ±20% to avoid thundering herd on reconnect
    var jitter = ms * (0.8 + Math.random() * 0.4);
    return Math.round(jitter);
  }

  function enqueue(item) {
    item.status = item.status || 'pending';
    item.created_at = item.created_at || new Date().toISOString();
    item.attempts = item.attempts || 0;
    item.next_retry_at = item.next_retry_at || null;
    item.last_error = item.last_error || null;
    return withStore(STORE_QUEUE, 'readwrite', function (store) {
      return store.add(item);
    });
  }

  function _allRows() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_QUEUE, 'readonly');
        var req = tx.objectStore(STORE_QUEUE).getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function listPending() {
    // Active queue for badge / manual Sync now (not abandoned/synced)
    return _allRows().then(function (rows) {
      var out = rows.filter(function (r) {
        return r.status === 'pending' || r.status === 'failed';
      });
      out.sort(function (a, b) {
        return (a.created_at || '').localeCompare(b.created_at || '');
      });
      return out;
    });
  }

  function listReadyToSync(nowMs) {
    // Auto-retry only when backoff elapsed
    var now = nowMs || Date.now();
    return listPending().then(function (rows) {
      return rows.filter(function (r) {
        if (!r.next_retry_at) return true;
        var t = Date.parse(r.next_retry_at);
        return isNaN(t) || t <= now;
      });
    });
  }

  function listAbandoned() {
    return _allRows().then(function (rows) {
      return rows.filter(function (r) { return r.status === 'abandoned'; });
    });
  }

  function markDone(id) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_QUEUE, 'readwrite');
        var store = tx.objectStore(STORE_QUEUE);
        var getReq = store.get(id);
        getReq.onsuccess = function () {
          var row = getReq.result;
          if (!row) {
            resolve(false);
            return;
          }
          row.status = 'synced';
          row.synced_at = new Date().toISOString();
          row.next_retry_at = null;
          row.last_error = null;
          store.put(row);
        };
        tx.oncomplete = function () { resolve(true); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function markFailed(id, error, opts) {
    opts = opts || {};
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_QUEUE, 'readwrite');
        var store = tx.objectStore(STORE_QUEUE);
        var getReq = store.get(id);
        getReq.onsuccess = function () {
          var row = getReq.result;
          if (!row) {
            resolve({ ok: false });
            return;
          }
          row.attempts = (row.attempts || 0) + 1;
          row.last_error = (error || '').toString().slice(0, 500);
          row.last_failed_at = new Date().toISOString();
          // Permanent server errors (validation / locked) should not burn the backoff clock.
          if (opts.permanent || row.attempts >= MAX_ATTEMPTS) {
            row.status = 'abandoned';
            row.next_retry_at = null;
          } else {
            row.status = 'failed';
            var delay = backoffMs(row.attempts);
            row.next_retry_at = new Date(Date.now() + delay).toISOString();
            row.backoff_ms = delay;
          }
          store.put(row);
          getReq._outcome = {
            ok: true,
            attempts: row.attempts,
            abandoned: row.status === 'abandoned',
            next_retry_at: row.next_retry_at,
            backoff_ms: row.backoff_ms || 0,
            permanent: !!opts.permanent,
          };
        };
        tx.oncomplete = function () {
          resolve(getReq._outcome || { ok: true });
        };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function resetForManualRetry(id) {
    // Sync now / Retry abandoned: clear backoff and allow another run
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_QUEUE, 'readwrite');
        var store = tx.objectStore(STORE_QUEUE);
        var getReq = store.get(id);
        getReq.onsuccess = function () {
          var row = getReq.result;
          if (!row) {
            resolve(false);
            return;
          }
          if (row.status === 'synced') {
            resolve(false);
            return;
          }
          if (row.status === 'abandoned') {
            row.attempts = 0;
          }
          row.status = 'pending';
          row.next_retry_at = null;
          store.put(row);
        };
        tx.oncomplete = function () { resolve(true); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function resetAbandonedAll() {
    return listAbandoned().then(function (rows) {
      var chain = Promise.resolve();
      rows.forEach(function (row) {
        chain = chain.then(function () { return resetForManualRetry(row.id); });
      });
      return chain.then(function () { return rows.length; });
    });
  }

  function saveBundle(bundle) {
    bundle.cached_at = new Date().toISOString();
    return withStore(STORE_BUNDLES, 'readwrite', function (store) {
      return store.put(bundle);
    });
  }

  function getBundle(loanRequestId) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_BUNDLES, 'readonly');
        var req = tx.objectStore(STORE_BUNDLES).get(Number(loanRequestId));
        req.onsuccess = function () { resolve(req.result || null); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function listBundles() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_BUNDLES, 'readonly');
        var req = tx.objectStore(STORE_BUNDLES).getAll();
        req.onsuccess = function () {
          var rows = req.result || [];
          rows.sort(function (a, b) {
            return String(b.cached_at || '').localeCompare(String(a.cached_at || ''));
          });
          resolve(rows);
        };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function saveDraft(key, data) {
    return withStore(STORE_DRAFTS, 'readwrite', function (store) {
      return store.put({ key: key, data: data, updated_at: new Date().toISOString() });
    });
  }

  function getDraft(key) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_DRAFTS, 'readonly');
        var req = tx.objectStore(STORE_DRAFTS).get(key);
        req.onsuccess = function () { resolve(req.result ? req.result.data : null); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function pendingCount() {
    return listPending().then(function (rows) { return rows.length; });
  }

  function queueStats() {
    return _allRows().then(function (rows) {
      var stats = { pending: 0, failed: 0, abandoned: 0, synced: 0, ready: 0 };
      var now = Date.now();
      rows.forEach(function (r) {
        if (r.status === 'pending') stats.pending += 1;
        else if (r.status === 'failed') stats.failed += 1;
        else if (r.status === 'abandoned') stats.abandoned += 1;
        else if (r.status === 'synced') stats.synced += 1;
        if (r.status === 'pending' || r.status === 'failed') {
          if (!r.next_retry_at || Date.parse(r.next_retry_at) <= now) stats.ready += 1;
        }
      });
      return stats;
    });
  }

  global.CollateralOfflineDB = {
    MAX_ATTEMPTS: MAX_ATTEMPTS,
    BASE_BACKOFF_MS: BASE_BACKOFF_MS,
    MAX_BACKOFF_MS: MAX_BACKOFF_MS,
    backoffMs: backoffMs,
    enqueue: enqueue,
    listPending: listPending,
    listReadyToSync: listReadyToSync,
    listAbandoned: listAbandoned,
    markDone: markDone,
    markFailed: markFailed,
    resetForManualRetry: resetForManualRetry,
    resetAbandonedAll: resetAbandonedAll,
    saveBundle: saveBundle,
    getBundle: getBundle,
    listBundles: listBundles,
    saveDraft: saveDraft,
    getDraft: getDraft,
    pendingCount: pendingCount,
    queueStats: queueStats,
  };
})(window);
