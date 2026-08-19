/* Apply and toggle staff-hub theme. Storage key: decsi-hub-theme */
(function () {
  var KEY = 'decsi-hub-theme';

  function preferred() {
    try {
      var stored = localStorage.getItem(KEY);
      if (stored === 'dark' || stored === 'light') return stored;
    } catch (e) { /* ignore */ }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark' : 'light';
  }

  function apply(theme) {
    var dark = theme === 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#082116' : '#064420');
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
      btn.setAttribute('aria-label', dark ? 'Use light theme' : 'Use dark theme');
      btn.title = dark ? 'Light theme' : 'Dark theme';
    });
  }

  function save(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* ignore */ }
  }

  window.decsiHubTheme = {
    apply: apply,
    current: preferred,
    toggle: function () {
      var next = preferred() === 'dark' ? 'light' : 'dark';
      save(next);
      apply(next);
      return next;
    }
  };

  apply(preferred());

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-theme-toggle]');
    if (!btn) return;
    e.preventDefault();
    window.decsiHubTheme.toggle();
  });
})();
