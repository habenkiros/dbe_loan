const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://127.0.0.1:8000';
const OUT = path.join(__dirname, 'screenshots');

async function shot(page, name, fullPage = true) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
  console.log('saved', name, page.url());
}

async function login(page, user, pass) {
  await page.goto(`${BASE}/login/`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="username"]', user);
  await page.fill('input[name="password"]', pass);
  await page.click('button[type="submit"], input[type="submit"]');
  await page.waitForTimeout(1500);
  console.log('logged in as', user, '->', page.url());
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await (await browser.newContext({
    viewport: { width: 1440, height: 900 },
  })).newPage();

  // Officer screens
  await login(page, 'zemeo', 'Demo@2026');
  const officerRoutes = [
    ['05-documents', '/loan_request/15919/documents/', true],
    ['06-appraisal-step1', '/loan_request/15919/appraisal/step/1/', true],
    ['06-appraisal-step2', '/loan_request/15919/appraisal/step/2/', true],
    ['06-appraisal-step3', '/loan_request/15919/appraisal/step/3/', true],
    ['06-appraisal-step4', '/loan_request/15919/appraisal/step/4/', true],
    ['06-appraisal-step5', '/loan_request/15919/appraisal/step/5/', true],
    ['06-appraisal-step6', '/loan_request/15919/appraisal/step/6/', true],
    ['06-appraisal-step7', '/loan_request/15919/appraisal/step/7/', true],
    ['16-create-loan', '/create_loan_request/', true],
    ['22-officer-home', '/', false],
  ];
  for (const [name, route, full] of officerRoutes) {
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(800);
      if (page.url().includes('/login/')) {
        await login(page, 'zemeo', 'Demo@2026');
        await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(800);
      }
      await shot(page, name, full);
    } catch (e) {
      console.log('fail', name, e.message);
    }
  }

  // Branch manager / reports
  await login(page, 'tsigeat', 'Demo@2026');
  for (const [name, route, full] of [
    ['14-reports', '/view_report/', false],
    ['16b-bm-create-loan', '/create_loan_request/', true],
    ['23-bm-home', '/', false],
  ]) {
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(800);
      await shot(page, name, full);
    } catch (e) {
      console.log('fail', name, e.message);
    }
  }

  // Ops manager queue
  await login(page, 'Abrehaley', 'Demo@2026');
  try {
    await page.goto(`${BASE}/view_loan_requests_operation_manager/`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    await shot(page, '24-ops-queue', false);
  } catch (e) {
    console.log('fail ops', e.message);
  }

  console.log('done');
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
