#!/usr/bin/env node
/**
 * Recapture staff create/detail + Digital Apply wizard steps.
 * Usage: node capture_manual_shots_fixup.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const OUT = path.resolve(__dirname, 'screenshots');
const BASE = 'http://127.0.0.1:8000';
const PORT = 9334;

const DETAILS = 'a951fa0c-3f9a-496d-a2e1-f8162c58a3fa';
const DOCS = '3ca15584-08b7-4466-9672-f810555104b3';
const PAY = '1a957612-4e0f-4bd0-8320-5b0580e0e026';
const SUBMITTED = 'd4cb9156-7c63-4043-8303-6356a41a75c4';
const LOAN_ID = 86;

fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
            reject(new Error(d.slice(0, 200)));
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
      this.ws.onerror = reject;
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

async function waitForDevtools() {
  for (let i = 0; i < 40; i++) {
    try {
      return await httpJson('GET', '/json/version');
    } catch (_) {
      await sleep(250);
    }
  }
  throw new Error('devtools not ready');
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
  return httpJson('PUT', '/json/new?about:blank');
}

async function main() {
  const userData = `/tmp/chrome-manual-fixup-${Date.now()}`;
  fs.mkdirSync(userData, { recursive: true });
  const chrome = spawn(
    'google-chrome',
    [
      '--headless=new',
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
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
      await cdp.send('Page.navigate', { url });
      await sleep(1800);
    }
    async function shot(name) {
      await cdp.send('Runtime.evaluate', { expression: 'window.scrollTo(0,0)' });
      await sleep(250);
      const { data } = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        fromSurface: true,
      });
      const file = path.join(OUT, name);
      fs.writeFileSync(file, Buffer.from(data, 'base64'));
      console.log('wrote', name, fs.statSync(file).size);
    }
    async function type(selector, value) {
      const expr = `(() => { const el=document.querySelector(${JSON.stringify(selector)}); if(!el) return false; el.focus(); el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); return true; })()`;
      return (await cdp.send('Runtime.evaluate', { expression: expr })).result.value;
    }
    async function click(selector) {
      const expr = `(() => { const el=document.querySelector(${JSON.stringify(selector)}); if(!el) return false; el.click(); return true; })()`;
      return (await cdp.send('Runtime.evaluate', { expression: expr })).result.value;
    }
    async function href() {
      return (await cdp.send('Runtime.evaluate', { expression: 'location.href' })).result.value;
    }
    async function loginStaff(user, pass) {
      await cdp.send('Network.clearBrowserCookies');
      await goto(`${BASE}/hub/login/`);
      await type('input[name="username"], #id_username', user);
      await type('input[name="password"], #id_password', pass);
      await click('button[type="submit"], input[type="submit"]');
      await sleep(2500);
      console.log('staff', user, await href());
    }

    // Branch manager: create loan + online loan detail
    await loginStaff('bm.mekele', 'ManualShot1!');
    await goto(`${BASE}/hub/create_loan_request/`);
    console.log('create url', await href());
    await shot('H-08_create_loan.png');

    await goto(`${BASE}/hub/loan_request_detail/${LOAN_ID}/`);
    console.log('detail url', await href());
    await shot('H-09_loan_detail.png');

    await goto(`${BASE}/hub/online_loan_intake/`);
    await shot('H-18_online_intake.png');

    await goto(`${BASE}/hub/view_loan_requests/`);
    await shot('H-07_loan_requests.png');

    // Applicant wizard
    await cdp.send('Network.clearBrowserCookies');
    await goto(`${BASE}/login/`);
    await type('input[name="login_id"], #id_login_id, input[type="text"]', '0914220481');
    await type('input[name="password"], #id_password, input[type="password"]', 'ManualShot1!');
    await click('button[type="submit"], input[type="submit"]');
    await sleep(2400);
    console.log('applicant', await href());

    await goto(`${BASE}/home/`);
    await sleep(1000);
    await shot('C-04_home_applications.png');

    await goto(`${BASE}/apply/new/`);
    await sleep(1200);
    await shot('C-05_apply_start.png');

    await goto(`${BASE}/apply/${DETAILS}/details/`);
    await sleep(1500);
    console.log('details', await href());
    await shot('C-05_apply_details.png');

    await goto(`${BASE}/apply/${DOCS}/documents/`);
    await sleep(1500);
    console.log('docs', await href());
    await shot('C-06_apply_documents.png');

    await goto(`${BASE}/apply/${PAY}/payment/`);
    await sleep(1500);
    console.log('pay', await href());
    await shot('C-07_apply_payment.png');

    await goto(`${BASE}/apply/${SUBMITTED}/`);
    await sleep(1500);
    await shot('C-09_apply_status.png');

    await goto(`${BASE}/apply/${SUBMITTED}/schedule/`);
    await sleep(1200);
    await shot('C-13_apply_schedule.png');

    cdp.close();
  } finally {
    chrome.kill('SIGKILL');
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
