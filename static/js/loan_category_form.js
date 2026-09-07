(function () {
  function applyPolicy(data) {
    var mode = document.getElementById('id_appraisal_mode');
    var req = document.getElementById('id_requires_collateral');
    var coll = document.getElementById('id_allowed_collateral');
    if (!data) return;
    if (mode && data.appraisal_mode) {
      mode.value = data.appraisal_mode;
    }
    if (req) {
      req.checked = !!data.requires_collateral;
    }
    if (coll) {
      var ids = {};
      (data.collaterals || []).forEach(function (row) { ids[String(row.id)] = true; });
      Array.prototype.forEach.call(coll.options, function (opt) {
        opt.selected = !!ids[opt.value];
      });
      coll.disabled = !data.requires_collateral;
    }
  }

  function bind(url) {
    var family = document.getElementById('id_product_family');
    if (!family || !url) return;
    family.addEventListener('change', function () {
      var q = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'family=' + encodeURIComponent(family.value);
      fetch(q, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) { if (data && data.ok) applyPolicy(data); })
        .catch(function () {});
    });
    var req = document.getElementById('id_requires_collateral');
    var coll = document.getElementById('id_allowed_collateral');
    if (req && coll) {
      coll.disabled = !req.checked;
      req.addEventListener('change', function () {
        coll.disabled = !req.checked;
        if (!req.checked) {
          Array.prototype.forEach.call(coll.options, function (opt) { opt.selected = false; });
        }
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var el = document.getElementById('loan-category-form');
    bind(el && el.getAttribute('data-policy-url'));
  });
})();
