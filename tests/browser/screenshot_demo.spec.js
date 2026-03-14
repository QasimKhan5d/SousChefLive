import { test } from '@playwright/test';

import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREENSHOT_DIR = path.resolve(__dirname, '../../artifacts/demo-screenshots');

test.describe('Demo Screenshot Capture', () => {
  test('capture landing page', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/01-landing.png`, fullPage: true });
  });

  test('capture cooking screen', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/02-cooking-initial.png`, fullPage: true });
  });

  test('capture cooking screen with demo speed enabled', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1000);
    await page.check('#checkbox-demo-speed');
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/03-cooking-demo-speed.png`, fullPage: true });
  });

  test('capture session badge and bottom panel', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);
    const badge = page.locator('#bottom-panel');
    await badge.screenshot({ path: `${SCREENSHOT_DIR}/04-session-badge.png` });
  });

  test('capture top bar chips', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1500);
    const topbar = page.locator('#top-bar');
    await topbar.screenshot({ path: `${SCREENSHOT_DIR}/05-top-bar-chips.png` });
  });
});
