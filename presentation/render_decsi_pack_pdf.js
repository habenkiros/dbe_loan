/**
 * Render DECSI management pack HTMLs to A4 PDFs via Playwright.
 * Usage: node render_decsi_pack_pdf.js
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;

const JOBS = [
  {
    html: 'decsi_cover_letter.html',
    pdf: 'DECSI_Cover_Letter.pdf',
    format: 'A4',
  },
  {
    html: 'decsi_loan_hub_proposal_document.html',
    pdf: 'DECSI_AI_Credit_Intelligence_Proposal.pdf',
    format: 'A4',
  },
  {
    html: 'decsi_financial_proposal.html',
    pdf: 'DECSI_Financial_Proposal.pdf',
    format: 'A4',
  },
  {
    html: 'decsi_technical_specification.html',
    pdf: 'DECSI_Technical_Specification.pdf',
    format: 'A4',
  },
  {
    html: 'decsi_management_committee_deck.html',
    pdf: 'DECSI_Management_Committee_Presentation.pdf',
    format: 'A4',
    landscape: true,
  },
];

async function render(browser, job) {
  const htmlPath = path.join(ROOT, job.html);
  const pdfPath = path.join(ROOT, job.pdf);
  if (!fs.existsSync(htmlPath)) {
    throw new Error('Missing ' + htmlPath);
  }
  const page = await browser.newPage();
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle', timeout: 120000 });
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
