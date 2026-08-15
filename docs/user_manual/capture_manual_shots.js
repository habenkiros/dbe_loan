#!/usr/bin/env node
/**
 * Capture authenticated hub + Digital Apply screenshots via Chrome CDP.
 * Usage: node capture_manual_shots.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const OUT = path.resolve(__dirname, 'screenshots');
const BASE = process.env.MANUAL_BASE || 'http://127.0.0.1:8000';
const PORT = Number(process.env.CDP_PORT || 9333);
const STAFF_USER = process.env.STAFF_USER || 'admin';
const STAFF_PASS = process.env.STAFF_PASS || 'ManualShot1!';
const APP_LOGIN = process.env.APP_LOGIN || '0914220481';
const APP_PASS = process.env.APP_PASS || 'ManualShot1!';
const DRAFT_UUID = process.env.DRAFT_UUID || '5c51101a-8c03-4fa0-bdc0-e28aa5f9ed68';
const SUBMITTED_UUID = process.env.SUBMITTED_UUID || 'd4cb9156-7c63-4043-8303-6356a41a75c4';

fs.mkdirSync(OUT, { recursive: true });

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function httpJson(method, urlPath) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port: PORT, path: urlPath, method },
      (res) => {
        let d = '';
        res.on('data', (c) => (d += c));
        res.on('end', () => {
          try {
            resolve(JSON.parse(d));
          } catch (e) {
            reject(new Error(`Bad JSON from ${method} ${urlPath}: ${d.slice(0, 200)}`));
          }
        });
      }
    );
    req.on('error', reject);
    req.end();
  });
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    };
    this.ready = new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = (e) => reject(e);
    });
  }
  async send(method, params = {}) {
    await this.ready;
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  close() {
    try {
      this.ws.close();
    } catch (_) {}
  }
}

async function waitForDevtools(retries = 40) {
  for (let i = 0; i < retries; i++) {
    try {
      return await httpJson('GET', '/json/version');
    } catch (_) {
      await sleep(250);
    }
  }
  throw new Error('Chrome DevTools not ready on port ' + PORT);
}

async function getPageTarget() {
  for (let i = 0; i < 20; i++) {
    const targets = await httpJson('GET', '/json/list');
    const page = (targets || []).find(
      (t) => t.type === 'page' && t.webSocketDebuggerUrl && !String(t.url || '').startsWith('chrome')
    );
    if (page) return page;
    await sleep(250);
  }
  // Chrome 120+ requires PUT for /json/new
  return httpJson('PUT', '/json/new?about:blank');
}

async function main() {
  const userData = `/tmp/chrome-manual-shots-${Date.now()}`;
  fs.mkdirSync(userData, { recursive: true });
  const chrome = spawn(
    'google-chrome',
    [
      '--headless=new',
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      '--force-device-scale-factor=1',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userData}`,
      '--window-size=1440,1100',
      'about:blank',
    ],
    { stdio: 'ignore' }
  );

  try {
    await waitForDevtools();
    const page = await getPageTarget();
    if (!page || !page.webSocketDebuggerUrl) {
      throw new Error('No page target: ' + JSON.stringify(page));
    }
    console.log('page target', page.id, page.url);

    const cdp = new Cdp(page.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 1100,
      deviceScaleFactor: 1,
      mobile: false,
    });

    async function goto(url) {
      const nav = cdp.send('Page.navigate', { url });
      await Promise.race([nav, sleep(15000)]);
      await sleep(1600);
    }

    async function shot(name) {
      await cdp.send('Runtime.evaluate', { expression: 'window.scrollTo(0,0)' });
      await sleep(250);
      const { data } = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        fromSurface: true,
        captureBeyondViewport: false,
      });
      const file = path.join(OUT, name);
      fs.writeFileSync(file, Buffer.from(data, 'base64'));
      console.log('wrote', name, fs.statSync(file).size);
    }

    async function type(selector, value) {
      const expr = `
        (() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return false;
          el.focus();
          el.value = ${JSON.stringify(value)};
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        })()
      `;
      return (await cdp.send('Runtime.evaluate', { expression: expr })).result.value;
    }

    async function click(selector) {
      const expr = `
        (() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return false;
          el.click();
          return true;
        })()
      `;
      return (await cdp.send('Runtime.evaluate', { expression: expr })).result.value;
    }

    async function href() {
      return (await cdp.send('Runtime.evaluate', { expression: 'location.href' })).result.value;
    }

    // --- Public / customer ---
    await goto(`${BASE}/`);
    await shot('C-01_landing.png');

    await goto(`${BASE}/register/`);
    await shot('C-02_register.png');

    await goto(`${BASE}/login/`);
    await shot('C-03_login.png');

    await goto(`${BASE}/help/`);
    await shot('C-11_help.png');

    // --- Staff login ---
    await goto(`${BASE}/hub/login/`);
    await shot('H-01_hub_login.png');
    await type('input[name="username"], #id_username', STAFF_USER);
    await type('input[name="password"], #id_password', STAFF_PASS);
    await click('button[type="submit"], input[type="submit"]');
    await sleep(2800);
    console.log('staff url', await href());
    await shot('H-04_hub_home.png');

    const staffHref = await href();
    if (String(staffHref).includes('mfa')) {
      console.log('MFA blocked further staff shots — disable MFA for admin capture user');
    } else {
      for (const [url, name] of [
        [`${BASE}/hub/view_loan_requests/`, 'H-07_loan_requests.png'],
        [`${BASE}/hub/create_loan_request/`, 'H-08_create_loan.png'],
        [`${BASE}/hub/online_loan_intake/`, 'H-18_online_intake.png'],
        [`${BASE}/hub/manage_applicant_portal/`, 'H-19_digital_apply_settings.png'],
        [`${BASE}/hub/delegations/`, 'H-23_delegations.png'],
        [`${BASE}/hub/help/`, 'H-06_help.png'],
        [`${BASE}/hub/view_loan_requests_manager/?queue=my_votes`, 'H-15_approval_queue.png'],
      ]) {
        await goto(url);
        console.log('staff page', name, await href());
        await shot(name);
      }

      await goto(`${BASE}/hub/view_loan_requests/`);
      const detail = await cdp.send('Runtime.evaluate', {
        expression: `
          (() => {
            const a = [...document.querySelectorAll('a[href]')].find(a =>
              /loan_request|loan\\/|view_loan|detail/i.test(a.href)
            );
            return a ? a.href : '';
          })()
        `,
      });
      if (detail.result.value) {
        await goto(detail.result.value);
        await shot('H-09_loan_detail.png');
      } else {
        console.log('no loan detail link found');
      }
    }

    // --- Applicant login + virtual loan apply flow ---
    await cdp.send('Network.clearBrowserCookies');
    await goto(`${BASE}/login/`);
    await type('input[name="login_id"], #id_login_id, input[type="text"]', APP_LOGIN);
    await type('input[name="password"], #id_password, input[type="password"]', APP_PASS);
    await click('button[type="submit"], input[type="submit"]');
    await sleep(2400);
    console.log('applicant url', await href());

    await goto(`${BASE}/home/`);
    await sleep(1200);
    await shot('C-04_home_applications.png');

    await goto(`${BASE}/apply/new/`);
    await sleep(1500);
    await shot('C-05_apply_start.png');

    await goto(`${BASE}/apply/${DRAFT_UUID}/details/`);
    await sleep(1500);
    await shot('C-05_apply_details.png');

    await goto(`${BASE}/apply/${DRAFT_UUID}/documents/`);
    await sleep(1500);
    await shot('C-06_apply_documents.png');

    await goto(`${BASE}/apply/${DRAFT_UUID}/payment/`);
    await sleep(1500);
    await shot('C-07_apply_payment.png');

    await goto(`${BASE}/apply/${SUBMITTED_UUID}/submit/`);
    await sleep(1200);
    await shot('C-08_apply_submit.png');

    await goto(`${BASE}/apply/${SUBMITTED_UUID}/`);
    await sleep(1500);
    await shot('C-09_apply_status.png');

    await goto(`${BASE}/apply/${SUBMITTED_UUID}/schedule/`);
    await sleep(1200);
    await shot('C-13_apply_schedule.png');

    await cdp.send('Network.clearBrowserCookies');
    await goto(`${BASE}/market-portal/`);
    await shot('M-01_market.png');

    cdp.close();
  } finally {
    chrome.kill('SIGKILL');
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
