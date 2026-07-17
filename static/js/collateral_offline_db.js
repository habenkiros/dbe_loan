/**
 * IndexedDB helpers for collateral offline field visits.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'collateral_offline_v1';
  var DB_VERSION = 1;
  var STORE_QUEUE = 'sync_queue';
  var STORE_BUNDLES = 'loan_bundles';
  var STORE_DRAFTS = 'field_drafts';

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

  function enqueue(item) {
    item.status = item.status || 'pending';
    item.created_at = item.created_at || new Date().toISOString();
    item.attempts = item.attempts || 0;
    return withStore(STORE_QUEUE, 'readwrite', function (store) {
      return store.add(item);
    });
  }

  function listPending() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_QUEUE, 'readonly');
        var store = tx.objectStore(STORE_QUEUE);
        var req = store.getAll();
        req.onsuccess = function () {
          var rows = (req.result || []).filter(function (r) {
            return r.status === 'pending' || r.status === 'failed';
          });
          rows.sort(function (a, b) {
            return (a.created_at || '').localeCompare(b.created_at || '');
          });
          resolve(rows);
        };
        req.onerror = function () { reject(req.error); };
      });
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
          store.put(row);
        };
        tx.oncomplete = function () { resolve(true); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function markFailed(id, error) {
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
          row.status = 'failed';
          row.attempts = (row.attempts || 0) + 1;
          row.last_error = (error || '').toString().slice(0, 500);
          store.put(row);
        };
        tx.oncomplete = function () { resolve(true); };
        tx.onerror = function () { reject(tx.error); };
      });
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

  global.CollateralOfflineDB = {
    enqueue: enqueue,
    listPending: listPending,
    markDone: markDone,
    markFailed: markFailed,
    saveBundle: saveBundle,
    getBundle: getBundle,
    saveDraft: saveDraft,
    getDraft: getDraft,
    pendingCount: pendingCount,
  };
})(window);
