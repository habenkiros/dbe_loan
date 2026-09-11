/* Credit Intelligence overview charts (Chart.js) */
(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    if (typeof Chart === 'undefined') return;

    var ciCharts = [];
    function isDarkTheme() {
      return document.documentElement.getAttribute('data-theme') === 'dark';
    }
    function themePalette() {
      var dark = isDarkTheme();
      return {
        legend: dark ? '#ececec' : '#0f2418',
        tick: dark ? '#c8c8c8' : '#5c6f63',
        grid: dark ? 'rgba(255,255,255,0.1)' : 'rgba(6, 68, 32, 0.08)'
      };
    }
    function chartDefaults() {
      var p = themePalette();
      return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 12, usePointStyle: true, padding: 14, color: p.legend }
          }
        }
      };
    }
    function makeChart(el, cfg) {
      var chart = new Chart(el, cfg);
      ciCharts.push(chart);
      return chart;
    }
    function restyleCharts() {
      var p = themePalette();
      Chart.defaults.color = p.legend;
      ciCharts.forEach(function (chart) {
        if (!chart || !chart.options) return;
        if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
          chart.options.plugins.legend.labels.color = p.legend;
        }
        var scales = chart.options.scales || {};
        Object.keys(scales).forEach(function (axis) {
          var s = scales[axis];
          if (s.ticks) s.ticks.color = p.tick;
          if (s.grid && s.grid.display !== false) s.grid.color = p.grid;
        });
        chart.update('none');
      });
    }
    Chart.defaults.color = themePalette().legend;
    document.documentElement.addEventListener('hub-theme-change', restyleCharts);

    var pipeline = window.CI_PIPELINE || {};
    var statusEl = document.getElementById('ciStatusDonut');
    if (statusEl) {
      makeChart(statusEl, {
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
        options: Object.assign({}, chartDefaults(), { cutout: '62%' })
      });
    }

    var bands = window.CI_SCORE_BANDS || [];
    var bandEl = document.getElementById('ciScoreBands');
    if (bandEl) {
      makeChart(bandEl, {
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
        options: Object.assign({}, chartDefaults(), {
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

    function etbTick(value) {
      if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
      if (value >= 1e6) return (value / 1e6).toFixed(1) + 'M';
      if (value >= 1e3) return (value / 1e3).toFixed(0) + 'k';
      return value;
    }

    var funnel = window.CI_FUNNEL || [];
    var funnelEl = document.getElementById('ciFunnelChart');
    if (funnelEl && funnel.length) {
      makeChart(funnelEl, {
        type: 'bar',
        data: {
          labels: funnel.map(function (s) { return s.label; }),
          datasets: [{
            label: 'Files',
            data: funnel.map(function (s) { return s.count || 0; }),
            backgroundColor: ['#1f6f8b', '#c98a12', '#2d6a4f', '#0f8a55'],
            borderRadius: 6,
            maxBarThickness: 28
          }]
        },
        options: Object.assign({}, chartDefaults(), {
          indexAxis: 'y',
          plugins: { legend: { display: false } },
          scales: {
            x: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            },
            y: { grid: { display: false } }
          }
        })
      });
    }

    var trend = window.CI_TREND || {};
    var trendEl = document.getElementById('ciTrendChart');
    if (trendEl && (trend.labels || []).length) {
      makeChart(trendEl, {
        type: 'bar',
        data: {
          labels: trend.labels,
          datasets: [
            {
              label: 'Approved files',
              data: trend.approved_count || [],
              backgroundColor: 'rgba(6, 68, 32, 0.82)',
              borderRadius: 6,
              maxBarThickness: 36,
              yAxisID: 'y'
            },
            {
              label: 'Approved book (ETB)',
              data: trend.approved_book || [],
              backgroundColor: 'rgba(31, 111, 139, 0.55)',
              borderRadius: 6,
              maxBarThickness: 36,
              yAxisID: 'y1'
            }
          ]
        },
        options: Object.assign({}, chartDefaults(), {
          scales: {
            x: { grid: { display: false } },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            },
            y1: {
              beginAtZero: true,
              position: 'right',
              ticks: { callback: etbTick },
              grid: { display: false }
            }
          }
        })
      });
    }

    var book = window.CI_BOOK || {};
    var bookEl = document.getElementById('ciBookChart');
    if (bookEl && (book.labels || []).length) {
      makeChart(bookEl, {
        type: 'bar',
        data: {
          labels: book.labels,
          datasets: [{
            label: 'ETB',
            data: book.values || [],
            backgroundColor: ['rgba(31, 111, 139, 0.82)', 'rgba(15, 138, 85, 0.82)'],
            borderRadius: 6,
            maxBarThickness: 48
          }]
        },
        options: Object.assign({}, chartDefaults(), {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: {
              beginAtZero: true,
              ticks: { callback: etbTick },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            }
          }
        })
      });
    }

    var branches = window.CI_BRANCHES || [];
    var branchEl = document.getElementById('ciBranchChart');
    if (branchEl) {
      makeChart(branchEl, {
        type: 'bar',
        data: {
          labels: branches.map(function (b) { return b.name; }),
          datasets: [
            {
              label: 'Loans',
              data: branches.map(function (b) { return b.count || 0; }),
              backgroundColor: 'rgba(6, 68, 32, 0.82)',
              borderRadius: 6,
              maxBarThickness: 28,
              yAxisID: 'y'
            },
            {
              label: 'Requested (ETB)',
              data: branches.map(function (b) { return b.amount || 0; }),
              backgroundColor: 'rgba(31, 111, 139, 0.5)',
              borderRadius: 6,
              maxBarThickness: 28,
              yAxisID: 'y1'
            }
          ]
        },
        options: Object.assign({}, chartDefaults(), {
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxRotation: 45, minRotation: 0 }
            },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
              grid: { color: 'rgba(6, 68, 32, 0.08)' }
            },
            y1: {
              beginAtZero: true,
              position: 'right',
              ticks: { callback: etbTick },
              grid: { display: false }
            }
          }
        })
      });
    }
    var collateralTypes = window.CI_COLLATERAL_TYPES || [];
    var collEl = document.getElementById('ciCollateralTypes');
    if (collEl && collateralTypes.length) {
      makeChart(collEl, {
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
        options: Object.assign({}, chartDefaults(), {
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 45 } },
            y: { beginAtZero: true, grid: { color: 'rgba(6, 68, 32, 0.08)' } }
          }
        })
      });
    }
    restyleCharts();
  });
})();
