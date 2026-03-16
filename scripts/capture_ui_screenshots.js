/**
 * Capture UI screenshots at key moments for agent inspection.
 * Run: DEPLOYED_URL=https://... node scripts/capture_ui_screenshots.js
 */
import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.DEPLOYED_URL || 'https://souschef-live-5z4a6smnda-uc.a.run.app';
const OUT_DIR = path.join(__dirname, '..', 'artifacts', 'screenshots');

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
  });
  const context = await browser.newContext({
    permissions: ['camera', 'microphone'],
  });
  const page = await context.newPage();

  try {
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(OUT_DIR, '01_landing.png'), fullPage: true });
    console.log('Saved 01_landing.png');

    await page.click('#btn-start');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(OUT_DIR, '02_cooking_screen.png'), fullPage: true });
    console.log('Saved 02_cooking_screen.png');

    await page.waitForTimeout(10000);
    await page.screenshot({ path: path.join(OUT_DIR, '03_after_10s.png'), fullPage: true });
    console.log('Saved 03_after_10s.png');

    const sessionText = await page.locator('#badge-session').textContent();
    const transcriptBody = await page.locator('#transcript-body').textContent();
    console.log('Session:', sessionText);
    console.log('Transcript preview:', (transcriptBody || '').slice(0, 200));
  } finally {
    await browser.close();
  }
  console.log('Done. Screenshots in', OUT_DIR);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
