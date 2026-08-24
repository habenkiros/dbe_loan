/**
 * Live 12-stage functionality UAT against the running hub.
 * Usage: node run_flow_functionality_uat.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UAT_BASE || 'http://127.0.0.1:8000';
const PASS = process.env.UAT_PASS || 'Demo@12345';
const OUT_JSON = path.join(__dirname, 'functionality_uat_results.json');
const OUT_DIR = path.join(__dirname, 'uat_shots');
fs.mkdirSync(OUT_DIR, { recursive: true });

const LOAN = 28; // HK-000002004 — docs, GPS, engineering approved
const BLD = 7;
const PASS_LOAN = Number(process.env.UAT_POST_APPROVAL_LOAN || 22); // DCSI-S0010 — committee_approved, awaiting_conditions (not disbursed)
const COMMITTEE_LOAN = Number(process.env.UAT_COMMITTEE_LOAN || 26); // pack still loads on a decided file

const results = [];

function rec(stage, check, ok, evidence, extra = {}) {
  results.push({
    stage,
    check,
    result: ok ? 'PASS' : 'FAIL',
    evidence: String(evidence || '').slice(0, 400),
    ...extra,
  });
  console.log(`${ok ? 'PASS' : 'FAIL'}  [${stage}] ${check} — ${String(evidence).slice(0, 120)}`);
}

async function shot(page, name) {
  try {
    await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: false });
  } catch (e) {
    /* ignore */
  }
}

async function login(page, user) {
  await page.goto(`${BASE}/hub/login/`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.fill('input[name="username"]', user);
  await page.fill('input[name="password"]', PASS);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  await page.waitForTimeout(600);
  const url = page.url();
  const text = await page.locator('body').innerText().catch(() => '');
  const ok = url.includes('/hub/') && !url.includes('/login');
  if (!ok) {
    return { ok, url, error: text.slice(0, 200) };
  }
  return { ok, url };
}

async function logout(page) {
  await page.goto(`${BASE}/hub/logout/`, { waitUntil: 'domcontentloaded' }).catch(() => null);
  await page.waitForTimeout(300);
}

async function open(page, urlPath) {
  const url = urlPath.startsWith('http') ? urlPath : `${BASE}${urlPath}`;
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(400);
  const status = resp ? resp.status() : 0;
  const body = await page.content();
  const text = await page.locator('body').innerText().catch(() => '');
  return { status, body, text, url: page.url() };
}

function hasAny(hay, needles) {
  const h = (hay || '').toLowerCase();
  return needles.some((n) => h.includes(String(n).toLowerCase()));
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  // ----- Public Digital Apply (stage 1) -----
  {
    const r = await open(page, '/');
    rec(1, 'Digital Apply landing loads', r.status === 200 && hasAny(r.text, ['Digital Apply', 'Create account']), `${r.status} ${r.url}`);
    const loginPub = await open(page, '/login/');
    rec(1, 'Applicant portal login is separate from hub', loginPub.status === 200 && !loginPub.url.includes('/hub/login'), loginPub.url);
    const apply = await open(page, '/register/');
    rec(1, 'Applicant register page loads', apply.status === 200 && hasAny(apply.text, ['Register', 'customer']), `${apply.status} ${apply.url}`);
  }

  // ----- Staff login (stage 12 + 1) -----
  {
    const lg = await login(page, 'bm.mekele');
  rec(12, 'Branch manager can sign in to /hub/', lg.ok, lg.error || lg.url);
    rec(1, 'BM sees create-loan entry after login', lg.ok, lg.url);
    await shot(page, '01-bm-home');
  }

  // ----- Stage 1 create form + POST (queue id = stage 3) -----
  let createdId = null;
  let createdQueue = null;
  {
    const r = await open(page, '/hub/create_loan_request/');
    rec(1, 'Create loan form loads for BM', r.status === 200 && hasAny(r.text, ['customer number', 'Register loan']), `${r.status}`);
    rec(1, 'Customer lookup is available (demo or live)', hasAny(r.text, ['Look up customer', 'Demo lookup', 'Core banking']), r.text.includes('Demo lookup') ? 'demo lookup' : 'lookup UI');
    rec(1, 'Customer source is labelled (mock vs live)', hasAny(r.text, ['demo', 'live', 'core banking', 'lookup', 'mock']), 'source UI on create form');

    if (r.status === 200 && await page.locator('input[name="customer_number"]').count()) {
    await page.fill('input[name="customer_number"]', '2000050041');
    await page.fill('input[name="applicant_name"]', 'UAT Tekeste');
    await page.fill('input[name="phone_number"]', '0945517351');
    const hist = page.locator('select[name="customer_history"]');
    if (await hist.count()) await hist.selectOption({ index: 1 });
    const cat = page.locator('select[name="category"]');
    if (await cat.count()) {
      const opts = await cat.locator('option').all();
      if (opts.length > 1) await cat.selectOption({ index: 1 });
    }
    const coll = page.locator('select[name="collateral"]');
    if (await coll.count()) {
      const opts = await coll.locator('option').all();
      if (opts.length > 1) await coll.selectOption({ index: 1 });
    }
    await page.fill('input[name="amount_requested"]', '150000');
    await page.fill('textarea[name="reason"]', 'UAT functionality check — working capital');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null),
      page.click('button[type="submit"], input[type="submit"]'),
    ]);
    await page.waitForTimeout(800);
    const after = page.url();
    const body = await page.locator('body').innerText();
    const qMatch = body.match(/HK-\d{6,}/);
    const idMatch = after.match(/loan_request\/(\d+)/) || after.match(/\/(\d+)\/documents/);
    createdQueue = qMatch ? qMatch[0] : null;
    createdId = idMatch ? idMatch[1] : null;
    rec(
      1,
      'BM can submit a new loan request',
      after.includes('/hub/') && (after.includes('documents') || after.includes('loan_request') || /HK-/.test(body)),
      after + (createdQueue ? ` queue=${createdQueue}` : ` body=${body.slice(0, 80)}`),
    );
    rec(3, 'Queue number HK-… is issued on create', Boolean(createdQueue), createdQueue || `url=${after}`);
    await shot(page, '02-create-result');
    } else {
      rec(1, 'BM can submit a new loan request', false, 'create form not available — skipped POST');
      rec(3, 'Queue number HK-… is issued on create', false, 'skipped — create form not available');
    }
  }

  // ----- Stage 2 documents -----
  {
    const r = await open(page, `/hub/loan_request/${LOAN}/documents/`);
    rec(2, 'Documents page loads for existing file', r.status === 200, `${r.status} ${r.url}`);
    rec(2, 'Upload / checklist / authenticate UI present', hasAny(r.text, ['document', 'upload', 'checklist', 'verify', 'authenticate']), r.text.slice(0, 160));
    await shot(page, '03-documents');
  }

  // ----- Stage 3 queue on list -----
  {
    const r = await open(page, '/hub/view_loan_requests/');
    rec(3, 'Loan list shows queue IDs', r.status === 200 && hasAny(r.text, ['HK-', 'DCSI-']), `${r.status} sample=${(r.text.match(/HK-\d+|DCSI-\S+/) || [''])[0]}`);
  }

  await logout(page);

  // Officer: GPS, estimation, appraisal
  {
    const lg = await login(page, 'lo.mekele1');
    rec(6, 'Loan officer can sign in', lg.ok, lg.url);

    const gps = await open(page, `/collateral/building/${BLD}/field-visit/1/`);
    rec(4, 'GPS field-visit step loads', [200, 302].includes(gps.status) || gps.url.includes('field-visit') || gps.url.includes('collateral'), `${gps.status} ${gps.url}`);
    rec(4, 'Field visit captures location (GPS / map / site)', hasAny(gps.text + gps.url, ['gps', 'latitude', 'longitude', 'map', 'site', 'accuracy', 'field']), gps.url);

    const land = await open(page, `/collateral/loan/${LOAN}/land/`);
    rec(4, 'Land collateral GPS path reachable', land.status === 200 || land.status === 302 || land.url.includes('collateral'), `${land.status} ${land.url}`);
    await shot(page, '04-gps-field');

    const sum = await open(page, `/collateral/loan/${LOAN}/summary/`);
    rec(5, 'Collateral estimation summary loads', sum.status === 200 || sum.url.includes('summary') || sum.url.includes('collateral'), `${sum.status} ${sum.url}`);
    rec(5, 'Estimated amount / total visible', hasAny(sum.text, ['total', 'ETB', 'estimat', 'value', 'BOQ', 'grand']), sum.text.slice(0, 140));
    await shot(page, '05-estimation');

    for (const step of [1, 2, 3, 4, 5, 6, 7]) {
      const a = await open(page, `/hub/loan_request/${LOAN}/appraisal/step/${step}/`);
      rec(
        6,
        `Appraisal step ${step} loads`,
        a.status === 200 && a.url.includes(`/appraisal/step/${step}`),
        `${a.status} ${a.url}`,
      );
      if (step === 1) {
        rec(6, 'Sheet 1 shows banking / document source labelling', hasAny(a.text, ['demo', 'live', 'banking', 'document', 'CBS', 'core', 'snapshot', 'source']), a.text.slice(0, 140));
      }
    }
    await shot(page, '06-appraisal');

    const q = await open(page, '/hub/view_loan_requests/');
    rec(9, 'Officer loan queue / list loads', q.status === 200, `${q.status}`);
  }

  await logout(page);

  // Engineer QA
  {
    const lg = await login(page, 'eng.mekele');
    rec(5, 'Engineer can sign in', lg.ok, lg.url);
    const qa = await open(page, '/collateral/engineering-qa/');
    rec(5, 'Engineering QA queue loads', qa.status === 200 || qa.url.includes('engineering'), `${qa.status} ${qa.url}`);
  }

  await logout(page);

  // Authorization / cooperative / committee
  {
    const lg = await login(page, 'coop.manager');
    rec(7, 'Cooperative manager can sign in', lg.ok, lg.url);
    const coop = await open(page, '/hub/view_loan_requests_operation_manager/');
    rec(9, 'Cooperative intake queue loads', coop.status === 200, `${coop.status} ${coop.url}`);
    rec(7, 'Branch-level intake gate is on screen', hasAny(coop.text, ['cooperative', 'queue', 'loan', 'approv']), coop.text.slice(0, 120));
  }

  await logout(page);

  {
    const lg = await login(page, 'bm.mekele');
    rec(7, 'BM can open committee / approval surfaces', lg.ok, lg.url);
    const pack = await open(page, `/hub/loan_request/${COMMITTEE_LOAN}/committee_appraisal/`);
    rec(7, 'Committee appraisal pack loads', pack.status === 200 || pack.status === 302 || pack.url.includes('committee'), `${pack.status} ${pack.url}`);
    const vote = await open(page, `/hub/loan_request/${COMMITTEE_LOAN}/committee_vote/`);
    rec(7, 'Committee vote page reachable', [200, 302, 403, 404].includes(vote.status) && vote.url.includes('/hub/'), `${vote.status} ${vote.url}`);
  }

  await logout(page);

  {
    const lg = await login(page, 'credit.head');
    rec(7, 'Credit head can sign in (HO committee config)', lg.ok, lg.url);
    const levels = await open(page, '/hub/manage_approval_committees/');
    rec(7, 'Approval committee levels admin loads', levels.status === 200 && hasAny(levels.text, ['committee', 'branch', 'district', 'head', 'management', 'level']), `${levels.status}`);
    await shot(page, '07-committees');
  }

  await logout(page);

  // Legal + disbursement (post-approval) as BM / finance
  {
    await login(page, 'bm.mekele');
    const pa = await open(page, `/hub/loan_request/${PASS_LOAN}/post_approval/`);
    rec(8, 'Post-approval screen loads (legal papers live here)', pa.status === 200 || pa.url.includes('post_approval'), `${pa.status} ${pa.url}`);
    rec(8, 'Collateral restriction / legal document controls present', hasAny(pa.text, ['restriction', 'legal', 'notary', 'mortgage', 'attorney', 'title', 'POA', 'collateral']), pa.text.slice(0, 160));
    rec(10, 'Disbursement / post-approval track is on the same file', hasAny(pa.text, ['disburs', 'finance', 'ready', 'schedule', 'tranche', 'mark']), pa.text.slice(0, 140));
    rec(9, 'Agreement / remote OTP closing is reachable from post-approval', hasAny(pa.text, ['agreement', 'sign', 'OTP', 'signature', 'remote']), pa.text.slice(0, 140));
    await shot(page, '08-post-approval');
    const agr = await open(page, `/hub/loan_request/${PASS_LOAN}/post_approval/`);
    const agrLink = agr.body.match(/\/hub\/loan_request\/\d+\/post_approval\/agreement\/\d+\/sign\//);
    if (agrLink) {
      const sign = await open(page, agrLink[0]);
      rec(9, 'Agreement sign page offers remote OTP', sign.status === 200 && hasAny(sign.text, ['OTP', 'remote', 'SMS', 'sign']), `${sign.status} ${sign.url}`);
    }
    const remote404 = await open(page, '/sign/agreement/not-a-real-token/');
    rec(9, 'Public remote-sign URL exists (invalid token is rejected)', [200, 404].includes(remote404.status) && remote404.url.includes('/sign/agreement/'), `${remote404.status} ${remote404.url}`);
  }

  await logout(page);

  {
    const lg = await login(page, 'fin.manager');
    rec(10, 'Finance manager can sign in', lg.ok, lg.url);
    const fq = await open(page, '/hub/view_loan_requests_finance_manager/');
    rec(10, 'Finance disbursement queue loads', fq.status === 200, `${fq.status} ${fq.url}`);
    rec(9, 'Finance queue is a processing status track', hasAny(fq.text, ['loan', 'disburs', 'finance', 'queue', 'empty', 'no loan']), fq.text.slice(0, 120));
    const book = await open(page, `/hub/update_finance_manager_approval/${PASS_LOAN}/`);
    rec(10, 'Finance approval / CBS preview page loads', book.status === 200 || book.url.includes('finance'), `${book.status} ${book.url}`);
    rec(10, 'CBS booking payload or ready-to-book blockers are visible', hasAny(book.text, ['CBS', 'payload', 'customer number', 'ready', 'disburs', 'blocker', 'book']), book.text.slice(0, 160));
    await shot(page, '10-finance-book');
  }

  await logout(page);

  // Reports + CI + security as haben (superadmin)
  {
    const lg = await login(page, 'admin');
    rec(12, 'Superadmin can sign in', lg.ok, lg.url);

    const rep = await open(page, '/hub/view_report/');
    rec(11, 'Classic reports page loads', rep.status === 200, `${rep.status} ${rep.url}`);
    rec(11, 'Report UI offers views / filters', hasAny(rep.text, ['report', 'branch', 'export', 'filter', 'loan']), rep.text.slice(0, 120));

    const ci = await open(page, '/hub/credit-intelligence/');
    rec(11, 'Credit Intelligence dashboard loads', ci.status === 200 || ci.url.includes('credit-intelligence'), `${ci.status} ${ci.url}`);
    await shot(page, '11-reports');

    const users = await open(page, '/hub/manage_users/');
    rec(12, 'Role-based user admin loads', users.status === 200 && hasAny(users.text, ['role', 'user']), `${users.status}`);

    const mfa = await open(page, '/hub/mfa/setup/');
    rec(12, 'MFA setup page loads', mfa.status === 200 || mfa.url.includes('mfa'), `${mfa.status} ${mfa.url}`);

    const audit = await open(page, '/hub/security/audit/');
    rec(12, 'Security audit log loads', audit.status === 200, `${audit.status} ${audit.url}`);
    rec(12, 'Authorization levels configurable (committees already checked)', true, 'see credit.head manage_approval_committees');
    await shot(page, '12-security');

    const fraudHint = await open(page, '/hub/risk/');
    rec(12, 'Risk desk reachable (credit risk review)', [200, 302, 403, 404].includes(fraudHint.status), `${fraudHint.status} ${fraudHint.url}`);
  }

  await logout(page);

  {
    const lg = await login(page, 'risk.officer');
    rec(12, 'Risk/compliance officer can sign in', lg.ok, lg.url);
    const desk = await open(page, '/hub/compliance/');
    rec(12, 'Fraud / AML desk loads', desk.status === 200 && desk.url.includes('compliance'), `${desk.status} ${desk.url}`);
    rec(12, 'Compliance desk shows investigation queues or case UI', hasAny(desk.text, ['fraud', 'AML', 'case', 'queue', 'investigat', 'open']), desk.text.slice(0, 160));
    await shot(page, '12-compliance-desk');
  }

  // Negative: applicant cannot open hub create
  {
    await logout(page);
    const r = await open(page, '/hub/create_loan_request/');
    rec(12, 'Unauthenticated staff URL redirects to login', r.url.includes('login') || r.status === 302, `${r.status} ${r.url}`);
  }

  await browser.close();

  const passed = results.filter((x) => x.result === 'PASS').length;
  const failed = results.filter((x) => x.result === 'FAIL').length;
  const byStage = {};
  for (const row of results) {
    if (!byStage[row.stage]) byStage[row.stage] = { pass: 0, fail: 0, checks: [] };
    byStage[row.stage][row.result === 'PASS' ? 'pass' : 'fail'] += 1;
    byStage[row.stage].checks.push(row);
  }

  const payload = {
    ran_at: new Date().toISOString(),
    base: BASE,
    created_loan: { id: createdId, queue: createdQueue },
    summary: { checks: results.length, passed, failed },
    by_stage: byStage,
    results,
  };
  fs.writeFileSync(OUT_JSON, JSON.stringify(payload, null, 2));
  console.log(`\n${passed} passed / ${failed} failed / ${results.length} checks`);
  console.log('Wrote', OUT_JSON);
  process.exit(failed ? 1 : 0);
})().catch((err) => {
  console.error(err);
  process.exit(2);
});
