/**
 * Floating Credit Intelligence Assist — multi-turn story + file copilot.
 * Desk inbox is server-side (all files). Page loan is context, not a separate cache.
 */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  function csrfToken(fallback) {
    if (fallback) return fallback;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  ready(function () {
    var root = document.getElementById('decsi-agent-widget');
    if (!root) return;

    var apiUrl = root.getAttribute('data-api-url') || '';
    var inboxUrl = root.getAttribute('data-inbox-url') || '';
    var historyTpl = root.getAttribute('data-history-url-tpl') || '';
    var csrf = csrfToken(root.getAttribute('data-csrf') || '');
    var pageLoanId = root.getAttribute('data-page-loan-id') || '';
    var pageLoanCode = root.getAttribute('data-page-loan-code') || '';

    var launcher = root.querySelector('.decsi-agent-launcher');
    var closeBtn = root.querySelector('[data-agent-close]');
    var newBtn = root.querySelector('[data-agent-new]');
    var inboxBtn = root.querySelector('[data-agent-inbox]');
    var inboxBox = root.querySelector('[data-agent-inbox-list]');
    var inboxRows = root.querySelector('[data-agent-inbox-rows]');
    var log = root.querySelector('.decsi-agent-log');
    var form = root.querySelector('.decsi-agent-composer');
    var input = root.querySelector('.decsi-agent-composer textarea');
    var sendBtn = root.querySelector('.decsi-agent-send');
    var statusEl = root.querySelector('.decsi-agent-status');
    var typing = root.querySelector('.decsi-agent-typing');
    var storyBox = document.getElementById('decsi-agent-story');
    var storyBody = document.getElementById('decsi-agent-story-body');
    var storyStatus = document.getElementById('decsi-agent-story-status');

    var convoId = '';
    var historyLoaded = false;
    var inboxLoaded = false;
    var suppressPageBind = false;
    var inboxItems = [];

    function resetLocalThread() {
      convoId = '';
      historyLoaded = false;
      suppressPageBind = false;
    }

    function openPanel() {
      root.classList.add('is-open');
      if (inboxBox) inboxBox.hidden = false;
      if (input) input.focus();
      if (!inboxLoaded) {
        loadInbox(true);
      } else if (convoId && !historyLoaded) {
        loadHistory();
      }
    }

    function closePanel() {
      root.classList.remove('is-open');
    }

    function scrollLog() {
      if (log) log.scrollTop = log.scrollHeight;
    }

    function renderStory(story) {
      if (!storyBox || !storyBody) return;
      if (!story || (!story.applicant_name && !story.amount && story.status !== 'committed')) {
        storyBox.hidden = true;
        return;
      }
      storyBox.hidden = false;
      if (storyStatus) {
        var st = story.status || 'draft';
        var miss = (story.missing || []).join(', ');
        storyStatus.textContent = st + (miss ? ' · need ' + miss : '');
      }
      storyBody.textContent = story.summary || [
        'Applicant: ' + (story.applicant_name || '—'),
        'Amount: ' + (story.amount != null ? Number(story.amount).toLocaleString() + ' ETB' : '—'),
        'Purpose: ' + (story.reason || '—'),
      ].join('\n');
    }

    function appendMsg(role, content, tools) {
      if (!log) return;
      var wrap = document.createElement('div');
      wrap.className = 'decsi-agent-msg decsi-agent-msg--' + role;
      var bubble = document.createElement('div');
      bubble.className = 'decsi-agent-bubble';
      bubble.textContent = content || '';
      wrap.appendChild(bubble);
      if (tools && tools.length) {
        var ul = document.createElement('ul');
        ul.className = 'decsi-agent-tools';
        tools.forEach(function (t) {
          var li = document.createElement('li');
          var label = (t.tool || '') + (t.ok ? ' ✓' : ' ✗');
          if (t.detail) label += ' — ' + String(t.detail).slice(0, 120);
          li.textContent = label;
          var data = t.data || {};
          var links = data.links || {};
          function addLink(href, text) {
            if (!href) return;
            li.appendChild(document.createTextNode(' '));
            var a = document.createElement('a');
            a.href = href;
            a.textContent = text;
            a.target = '_self';
            li.appendChild(a);
          }
          addLink(links.detail_url, 'Loan');
          addLink(links.excel_export_url, 'Excel');
          addLink(links.pipeline_view_url, 'Pipeline');
          addLink(links.dashboard_url, 'Dashboard');
          ul.appendChild(li);
        });
        wrap.appendChild(ul);
      }
      log.appendChild(wrap);
      scrollLog();
    }

    function clearLog() {
      if (log) log.innerHTML = '';
    }

    function setBusy(busy) {
      if (sendBtn) sendBtn.disabled = busy;
      if (input) input.disabled = busy;
      if (typing) typing.classList.toggle('is-on', !!busy);
    }

    function seedWelcome() {
      if (pageLoanCode) {
        appendMsg(
          'assistant',
          'Credit Intelligence Assist — this file is ' + pageLoanCode + '.\n' +
            'Ask what’s blocking, the document checklist, appraisal coach, or a committee brief.\n' +
            'Inbox keeps every file’s chat on this desk. I will not attach documents, write appraisal, vote, or disburse.'
        );
        return;
      }
      appendMsg(
        'assistant',
        'Hi — I’m Credit Intelligence Assist.\n' +
          '• Inbox lists every chat on this desk (not just this browser tab)\n' +
          '• Branch managers: hold a draft story → confirm to create loans\n' +
          '• Officers / engineers / committee: blockers, KYC, docs, brief — vote and valuation stay in the UI\n\n' +
          'Ask by role — e.g. BM “loan for Acme 1.5m”, LO “register building for LOAN-CODE”.'
      );
    }

    function renderInbox() {
      if (!inboxRows) return;
      inboxRows.innerHTML = '';
      if (!inboxItems.length) {
        var empty = document.createElement('div');
        empty.className = 'decsi-agent-inbox-empty';
        empty.textContent = 'No saved chats yet. Send a message to start one.';
        inboxRows.appendChild(empty);
        return;
      }
      inboxItems.forEach(function (item) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'decsi-agent-inbox-item' + (String(item.id) === String(convoId) ? ' is-active' : '');
        var strong = document.createElement('strong');
        strong.textContent = item.title || ('Chat #' + item.id);
        var span = document.createElement('span');
        span.textContent = item.preview || item.loan_request_code || 'Open thread';
        btn.appendChild(strong);
        btn.appendChild(span);
        btn.addEventListener('click', function () {
          openConversation(item);
        });
        inboxRows.appendChild(btn);
      });
    }

    function pickInboxConversation(items) {
      if (!items || !items.length) return null;
      if (pageLoanId) {
        var match = items.filter(function (row) {
          return String(row.loan_request_id || '') === String(pageLoanId);
        })[0];
        if (match) return match;
      }
      return items[0];
    }

    function loadInbox(autoOpen) {
      if (!inboxUrl) {
        if (autoOpen) seedWelcome();
        return;
      }
      fetch(inboxUrl, { credentials: 'same-origin' })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          inboxLoaded = true;
          inboxItems = (data && data.ok && data.conversations) ? data.conversations : [];
          renderInbox();
          if (!autoOpen) return;
          var pick = pickInboxConversation(inboxItems);
          if (pick) {
            openConversation(pick);
          } else if (!historyLoaded && log && !log.children.length) {
            seedWelcome();
          }
        })
        .catch(function () {
          inboxLoaded = true;
          if (autoOpen && !historyLoaded) seedWelcome();
        });
    }

    function openConversation(item) {
      if (!item || !item.id) return;
      convoId = String(item.id);
      historyLoaded = false;
      suppressPageBind = !!(item.loan_request_id && String(item.loan_request_id) !== String(pageLoanId || ''));
      renderInbox();
      loadHistory();
    }

    function loadHistory() {
      if (!convoId || !historyTpl) return;
      var url = historyTpl.replace('{id}', encodeURIComponent(convoId));
      fetch(url, { credentials: 'same-origin' })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (!data || !data.ok) {
            resetLocalThread();
            seedWelcome();
            return;
          }
          historyLoaded = true;
          clearLog();
          var msgs = data.messages || [];
          if (!msgs.length) {
            seedWelcome();
          } else {
            msgs.forEach(function (m) {
              appendMsg(m.role, m.content, m.tools || []);
            });
          }
          renderStory(data.story);
          if (statusEl) {
            if (data.loan_request_code) {
              statusEl.textContent = 'Desk chat · ' + data.loan_request_code;
            } else if (pageLoanCode && !suppressPageBind) {
              statusEl.textContent = 'This file: ' + pageLoanCode;
            } else {
              statusEl.textContent = 'Desk inbox';
            }
          }
        })
        .catch(function () {
          /* keep local welcome */
        });
    }

    function resetChat(opts) {
      opts = opts || {};
      resetLocalThread();
      clearLog();
      seedWelcome();
      renderStory(null);
      renderInbox();
      if (statusEl) {
        if (opts.fromClear) {
          statusEl.textContent = 'New chat. Next message starts a desk thread.';
        } else if (pageLoanCode) {
          statusEl.textContent = 'This file: ' + pageLoanCode;
        } else {
          statusEl.textContent = '';
        }
      }
      if (input) {
        input.value = '';
        input.focus();
      }
    }

    function isClearCommand(text) {
      var t = (text || '').trim().toLowerCase();
      return (
        t === 'clear' ||
        t === 'clear cache' ||
        t === 'clear chat' ||
        t === 'reset cache' ||
        t === '/clear'
      );
    }

    function sendMessage(text) {
      text = (text || '').trim();
      if (!text) return;
      if (isClearCommand(text)) {
        resetChat({ fromClear: true });
        return;
      }
      if (!apiUrl) return;
      appendMsg('user', text);
      if (input) input.value = '';
      setBusy(true);

      fetch(apiUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
        },
        body: JSON.stringify({
          message: text,
          conversation_id: convoId || null,
          page_loan_id: suppressPageBind ? null : (pageLoanId || null),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          var data = result.data || {};
          if (data.conversation_id) {
            convoId = String(data.conversation_id);
            historyLoaded = true;
            loadInbox(false);
          }
          appendMsg('assistant', data.reply || data.error || 'No reply.', data.tools || []);
          renderStory(data.story);
          if (statusEl) {
            if (data.loan_request_code) {
              statusEl.textContent = 'Linked loan: ' + data.loan_request_code;
            } else if (pageLoanCode) {
              statusEl.textContent = 'This file: ' + pageLoanCode;
            } else if (data.story && data.story.status === 'ready') {
              statusEl.textContent = 'Draft ready — say confirm to create.';
            } else {
              statusEl.textContent = data.provider ? 'Provider: ' + data.provider : '';
            }
          }
        })
        .catch(function (err) {
          appendMsg(
            'assistant',
            'Could not reach the assistant. ' + (err && err.message ? err.message : '')
          );
        })
        .finally(function () {
          setBusy(false);
          if (input) input.focus();
        });
    }

    if (launcher) launcher.addEventListener('click', openPanel);
    if (closeBtn) closeBtn.addEventListener('click', closePanel);
    if (inboxBtn && inboxBox) {
      inboxBtn.addEventListener('click', function () {
        inboxBox.hidden = !inboxBox.hidden;
        if (!inboxBox.hidden) loadInbox(false);
      });
    }
    if (newBtn) {
      newBtn.addEventListener('click', function () {
        resetChat({ fromClear: true });
      });
    }
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        sendMessage(input && input.value);
      });
    }
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage(input.value);
        }
      });
    }

    root.querySelectorAll('[data-agent-chip]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openPanel();
        sendMessage(btn.getAttribute('data-agent-chip') || btn.textContent);
      });
    });

    if (log && !log.children.length) {
      seedWelcome();
    }
    if (statusEl && pageLoanCode && !statusEl.textContent) {
      statusEl.textContent = 'This file: ' + pageLoanCode;
    }

    try {
      var params = new URLSearchParams(window.location.search);
      if (
        params.get('agent') === '1' ||
        root.getAttribute('data-auto-open') === '1' ||
        window.__DECSI_AGENT_AUTO_OPEN
      ) {
        openPanel();
      }
    } catch (e) {}
  });
})();
