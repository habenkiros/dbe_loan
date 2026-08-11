/**
 * Idle session warning + keepalive for authenticated staff pages.
 * Expects window.SESSION_SECURITY = { timeout, warning, keepaliveUrl, logoutUrl }
 */
(function () {
  var cfg = window.SESSION_SECURITY;
  if (!cfg || !cfg.timeout || cfg.timeout <= 0) return;

  var timeoutMs = cfg.timeout * 1000;
  var warningMs = Math.min((cfg.warning || 120) * 1000, Math.max(timeoutMs - 1000, 1000));
  var lastActive = Date.now();
  var lastKeepalive = 0;
  var warned = false;
  var banner = null;
  var keepaliveMinGap = 60000;

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function ensureBanner() {
    if (banner) return banner;
    banner = document.createElement('div');
    banner.id = 'session-idle-banner';
    banner.setAttribute('role', 'alert');
    banner.style.cssText = [
      'display:none',
      'position:fixed',
      'z-index:99999',
      'left:50%',
      'bottom:24px',
      'transform:translateX(-50%)',
      'max-width:420px',
      'width:calc(100% - 32px)',
      'background:#fff8e6',
      'border:1px solid #e0c36a',
      'color:#5c4800',
      'padding:14px 16px',
      'border-radius:8px',
      'box-shadow:0 8px 24px rgba(0,0,0,.12)',
      'font:14px/1.4 Arial,sans-serif',
    ].join(';');
    banner.innerHTML =
      '<strong>Session expiring</strong>' +
      '<p style="margin:8px 0 12px">You will be signed out soon due to inactivity.</p>' +
      '<button type="button" id="session-stay-btn" style="background:#07ae18;color:#fff;border:0;padding:8px 12px;border-radius:5px;cursor:pointer;margin-right:8px">Stay signed in</button>' +
      '<button type="button" id="session-logout-btn" style="background:transparent;border:1px solid #999;padding:8px 12px;border-radius:5px;cursor:pointer">Sign out</button>';
    document.body.appendChild(banner);
    document.getElementById('session-stay-btn').addEventListener('click', function () {
      extendSession(true);
    });
    document.getElementById('session-logout-btn').addEventListener('click', function () {
      window.location.href = cfg.logoutUrl;
    });
    return banner;
  }

  function showWarning() {
    warned = true;
    ensureBanner().style.display = 'block';
  }

  function hideWarning() {
    warned = false;
    if (banner) banner.style.display = 'none';
  }

  function extendSession(force) {
    var now = Date.now();
    if (!force && now - lastKeepalive < keepaliveMinGap) return;
    lastKeepalive = now;
    fetch(cfg.keepaliveUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
      },
    })
      .then(function (r) {
        if (!r.ok) throw new Error('keepalive failed');
        return r.json();
      })
      .then(function () {
        lastActive = Date.now();
        hideWarning();
      })
      .catch(function () {
        if (force) window.location.href = cfg.logoutUrl;
      });
  }

  function onActivity() {
    lastActive = Date.now();
    extendSession(false);
    if (warned) extendSession(true);
  }

  ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'].forEach(function (evt) {
    document.addEventListener(evt, onActivity, { passive: true });
  });

  setInterval(function () {
    var idle = Date.now() - lastActive;
    if (idle >= timeoutMs) {
      window.location.href = cfg.logoutUrl;
      return;
    }
    if (idle >= timeoutMs - warningMs) {
      showWarning();
    }
  }, 5000);
})();
