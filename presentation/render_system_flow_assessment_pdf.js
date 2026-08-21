/**
 * Render system flow assessment HTMLs to A4 PDFs via Playwright.
 * Usage: node render_system_flow_assessment_pdf.js
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;

const JOBS = [
  {
    html: 'decsi_system_flow_assessment.html',
    pdf: 'DECSI_System_Flow_Assessment.pdf',
  },
  {
    html: 'system_flow_assessment_internal.html',
    pdf: 'System_Flow_Assessment_Internal.pdf',
  },
  {
    html: 'functionality_uat.html',
    pdf: 'Functionality_UAT_Results.pdf',
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
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
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
