/**
 * Render DBE iBOC / Credit Intelligence proposal HTMLs to A4 PDFs via Playwright.
 * Usage: node render_dbe_pack_pdf.js
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;

const JOBS = [
  {
    html: 'dbe_cover_letter.html',
    pdf: 'DBE_Cover_Letter.pdf',
    format: 'A4',
  },
  {
    html: 'dbe_loan_hub_proposal_document.html',
    pdf: 'DBE_AI_Credit_Intelligence_Proposal.pdf',
    format: 'A4',
  },
  {
    html: 'dbe_loan_hub_proposal.html',
    pdf: 'DBE_AI_Credit_Intelligence_Presentation.pdf',
    format: 'A4',
    landscape: true,
  },
  {
    html: 'dbe_ceo_briefing.html',
    pdf: 'DBE_CEO_Briefing.pdf',
    format: 'A4',
    landscape: true,
  },
  {
    html: 'dbe_server_specification.html',
    pdf: 'DBE_Server_Specification.pdf',
    format: 'A4',
  },
];

async function render(browser, job) {
  const htmlPath = path.join(ROOT, job.html);
  const pdfPath = path.join(ROOT, job.pdf);
  if (!fs.existsSync(htmlPath)) {
    throw new Error('Missing ' + htmlPath);
  }
  const page = await browser.newPage();
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle', timeout: 180000 });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: pdfPath,
    format: job.format,
    landscape: !!job.landscape,
    printBackground: true,
    preferCSSPageSize: !job.landscape,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });
  await page.close();
  const stat = fs.statSync(pdfPath);
  console.log('Wrote', job.pdf, '(' + Math.round(stat.size / 1024) + ' KB)');
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const job of JOBS) {
      await render(browser, job);
    }
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
