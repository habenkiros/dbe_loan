const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://127.0.0.1:8000';
const OUT = path.join(__dirname, 'screenshots');

async function shot(page, name, fullPage = true) {
  await page.waitForTimeout(800);
  // avoid capturing Django debug pages
  const html = await page.content();
  if (html.includes('UnboundLocalError') || html.includes('Exception Value')) {
    console.log('ERROR PAGE', name, page.url());
    return;
  }
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
  console.log('saved', name, page.url());
}

async function login(page, user, pass) {
  await page.goto(`${BASE}/login/`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="username"]', user);
  await page.fill('input[name="password"]', pass);
  await page.click('button[type="submit"], input[type="submit"]');
  await page.waitForTimeout(1200);
  console.log('login', user, page.url());
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();

  await login(page, 'zemeo', 'Demo@2026');
  for (const step of [1, 2, 3, 4, 5, 6, 7]) {
    await page.goto(`${BASE}/loan_request/15919/appraisal/step/${step}/`, { waitUntil: 'domcontentloaded' });
    await shot(page, `06-appraisal-step${step}`, true);
  }
  await page.goto(`${BASE}/loan_request_detail/15919/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '04b-officer-loan-detail', true);

  await login(page, 'gebrelibanosmt', 'Demo@2026');
  await page.goto(`${BASE}/loan_request/15919/documents/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '05-documents', true);
  await page.goto(`${BASE}/create_loan_request/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '16-create-loan', true);

  await login(page, 'haben', 'Demo@2026');
  await page.goto(`${BASE}/loan_request/15919/committee_appraisal/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '07-committee-pack', true);
  await page.goto(`${BASE}/collateral/loan/15919/evidence-pack/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '12-evidence-pack', true);
  await page.goto(`${BASE}/collateral/building/14/field-visit/1/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '10-field-visit', true);
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await shot(page, '02-dashboard-home', false);

  console.log('done');
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
