(function () {
  var shell = document.querySelector('.ap-shell');
  var toggle = document.querySelector('.ap-nav-toggle');
  if (!shell || !toggle) return;

  function setOpen(open) {
    shell.classList.toggle('nav-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }

  toggle.addEventListener('click', function () {
    setOpen(!shell.classList.contains('nav-open'));
  });

  document.querySelectorAll('.ap-nav a').forEach(function (link) {
    link.addEventListener('click', function () { setOpen(false); });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') setOpen(false);
  });

  window.addEventListener('resize', function () {
    if (window.matchMedia('(min-width: 721px)').matches) setOpen(false);
  });
})();
