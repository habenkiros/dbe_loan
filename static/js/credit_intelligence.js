/* Credit Intelligence overview charts (Chart.js) */
(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    if (typeof Chart === 'undefined') return;

    var chartDefaults = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { boxWidth: 12, usePointStyle: true, padding: 14 }
        }
      }
    };

    var pipeline = window.CI_PIPELINE || {};
    var statusEl = document.getElementById('ciStatusDonut');
    if (statusEl) {
      new Chart(statusEl, {
        type: 'doughnut',
        data: {
          labels: ['Approved', 'Pending', 'Rejected'],
          datasets: [{
            data: [
              pipeline.approved || 0,
              pipeline.pending || 0,
              pipeline.rejected || 0
            ],
            backgroundColor: ['#0f8a55', '#c98a12', '#c0392b'],
            borderWidth: 0,
            hoverOffset: 4
          }]
        },
        options: Object.assign({}, chartDefaults, { cutout: '62%' })
      });
    }

    var bands = window.CI_SCORE_BANDS || [];
    var bandEl = document.getElementById('ciScoreBands');
    if (bandEl) {
      new Chart(bandEl, {
        type: 'bar',
        data: {
          labels: bands.map(function (b) { return b.label || b.band; }),
          datasets: [{
            label: 'Applications',
            data: bands.map(function (b) { return b.count || 0; }),
            backgroundColor: ['#0f8a55', '#2d6a4f', '#c98a12', '#c0392b'],
            borderRadius: 6,
            maxBarThickness: 40
          }]
        },
        options: Object.assign({}, chartDefaults, {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            }
          }
        })
      });
    }

    var branches = window.CI_BRANCHES || [];
    var branchEl = document.getElementById('ciBranchChart');
    if (branchEl) {
      new Chart(branchEl, {
        type: 'bar',
        data: {
          labels: branches.map(function (b) { return b.name; }),
          datasets: [{
            label: 'Loans',
            data: branches.map(function (b) { return b.count || 0; }),
            backgroundColor: 'rgba(6, 68, 32, 0.82)',
            borderRadius: 6,
            maxBarThickness: 42
          }]
        },
        options: Object.assign({}, chartDefaults, {
          plugins: { legend: { display: false } },
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxRotation: 45, minRotation: 0 }
            },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            }
          }
        })
      });
    }
    var collateralTypes = window.CI_COLLATERAL_TYPES || [];
    var collEl = document.getElementById('ciCollateralTypes');
    if (collEl && collateralTypes.length) {
      new Chart(collEl, {
        type: 'bar',
        data: {
          labels: collateralTypes.map(function (b) { return b.name; }),
          datasets: [{
            label: 'Collateral value (ETB)',
            data: collateralTypes.map(function (b) { return b.value || 0; }),
            backgroundColor: 'rgba(31, 111, 139, 0.82)',
            borderRadius: 6,
            maxBarThickness: 42
          }]
        },
        options: Object.assign({}, chartDefaults, {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 45 } },
            y: { beginAtZero: true, grid: { color: 'rgba(6, 68, 32, 0.08)' } }
          }
        })
      });
    }
  });
})();
