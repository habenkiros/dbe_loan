const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://127.0.0.1:8000';
const OUT = path.join(__dirname, 'screenshots');
fs.mkdirSync(OUT, { recursive: true });

async function shot(page, name, fullPage = true) {
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(500);
  await page.screenshot({ path: file, fullPage });
  console.log('saved', name, page.url());
}

async function safeGoto(page, url) {
  const res = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(700);
  return res;
}

async function login(page, user, pass) {
  await safeGoto(page, `${BASE}/login/`);
  await page.fill('input[name="username"]', user);
  await page.fill('input[name="password"]', pass);
  await page.click('button[type="submit"], input[type="submit"]');
  await page.waitForTimeout(1200);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  const pages = [
    ['01-login', `${BASE}/login/`, false, false],
  ];

  // Login screen first
  await safeGoto(page, `${BASE}/login/`);
  await shot(page, '01-login', false);

  await login(page, 'haben', 'Demo@2026');
  await shot(page, '02-dashboard-home', false);

  const routes = [
    ['03-loan-list', '/view_loan_requests/', false],
    ['04-loan-detail', '/loan_request_detail/15919/', true],
    ['05-documents', '/loan_request/15919/documents/', true],
    ['06-appraisal-step1', '/loan_request/15919/appraisal/step/1/', true],
    ['06-appraisal-step2', '/loan_request/15919/appraisal/step/2/', true],
    ['06-appraisal-step3', '/loan_request/15919/appraisal/step/3/', true],
    ['06-appraisal-step4', '/loan_request/15919/appraisal/step/4/', true],
    ['06-appraisal-step5', '/loan_request/15919/appraisal/step/5/', true],
    ['06-appraisal-step6', '/loan_request/15919/appraisal/step/6/', true],
    ['06-appraisal-step7', '/loan_request/15919/appraisal/step/7/', true],
    ['07-committee-pack', '/loan_request/15919/committee_appraisal/', true],
    ['08-collateral-dashboard', '/collateral/', false],
    ['09-buildings', '/collateral/loan/15919/buildings/', true],
    ['10-field-visit', '/collateral/building/14/field-visit/1/', true],
    ['11-collateral-summary', '/collateral/loan/15919/summary/', true],
    ['12-evidence-pack', '/collateral/loan/15919/evidence-pack/', true],
    ['13-collateral-policy', '/collateral/settings/policy/', true],
    ['14-reports', '/view_report/', false],
    ['15-loan-categories', '/manage_loan_categories/', false],
    ['16-create-loan', '/create_loan_request/', true],
    ['17-notifications', '/notifications/', false],
    ['18-engineering-qa', '/collateral/engineering-qa/', false],
    ['19-field-checklist', '/collateral/field-checklist/', true],
    ['20-manage-users', '/manage_users/', false],
    ['21-manage-branches', '/manage_branches/', false],
  ];

  for (const [name, route, full] of routes) {
    try {
      await safeGoto(page, `${BASE}${route}`);
      // skip if bounced to login
      if (page.url().includes('/login/')) {
        console.log('auth-fail', name);
        await login(page, 'haben', 'Demo@2026');
        await safeGoto(page, `${BASE}${route}`);
      }
      await shot(page, name, full);
    } catch (e) {
      console.log('fail', name, e.message);
    }
  }

  console.log('done');
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
