(function () {
  var toggle = document.querySelector('.hub-nav-toggle');
  var nav = document.getElementById('hub-main-nav');
  if (!toggle || !nav) return;

  function closeDropdowns() {
    document.querySelectorAll('.dropdown.show').forEach(function (d) {
      d.classList.remove('show');
    });
  }

  function setOpen(open) {
    document.body.classList.toggle('nav-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    if (!open) closeDropdowns();
  }

  toggle.addEventListener('click', function () {
    setOpen(!document.body.classList.contains('nav-open'));
  });

  nav.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', function () {
      if (window.matchMedia('(max-width: 720px)').matches) setOpen(false);
    });
  });

  document.querySelectorAll('.dropbtn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var drop = this.closest('.dropdown');
      var open = document.querySelector('.dropdown.show');
      if (open && open !== drop) open.classList.remove('show');
      drop.classList.toggle('show');
    });
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.dropdown')) closeDropdowns();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') setOpen(false);
  });

  window.addEventListener('resize', function () {
    if (window.matchMedia('(min-width: 721px)').matches) setOpen(false);
  });
})();
