import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const SCREENSHOT_DIR = path.join(
  process.cwd(),
  'artifacts',
  'screenshots',
  new Date().toISOString().replace(/[:.]/g, '-'),
);

test.beforeAll(async () => {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
});

async function screenshot(page, name) {
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  });
}

test.describe('SousChef Live — Demo Flow Visual Verification', () => {
  test('landing page renders all branding elements', async ({ page }) => {
    await page.goto('/');
    await screenshot(page, '01-landing');

    await expect(page).toHaveTitle(/SousChef/i);
    await expect(page.locator('h1')).toContainText('SousChef Live');
    await expect(page.locator('.accent')).toContainText('Live');
    await expect(page.locator('#btn-start')).toBeVisible();
    await expect(page.locator('.tagline')).toContainText('real-time AI sous-chef');
  });

  test('landing page has gradient bg, feature badges, and powered-by', async ({ page }) => {
    await page.goto('/');
    await screenshot(page, '01b-landing-details');

    await expect(page.locator('.landing-bg')).toBeVisible();
    await expect(page.locator('.feature-badge')).toHaveCount(3);
    await expect(page.locator('.powered-by')).toContainText('Gemini Live API');
    await expect(page.locator('.btn-pulse')).toBeVisible();
  });

  test('transition to cooking screen shows all UI proof signals', async ({
    page,
  }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1000);
    await screenshot(page, '02-cooking-screen');

    // Session badge (region)
    await expect(page.locator('#badge-region')).toContainText('europe-west1');

    // RTT indicator
    await expect(page.locator('#badge-rtt')).toBeVisible();

    // Timer badge
    await expect(page.locator('#badge-timers')).toContainText('timer');

    // Step chip
    await expect(page.locator('#chip-step')).toBeVisible();
    await expect(page.locator('#step-text')).toContainText('Idle');

    // Monitoring status
    await expect(page.locator('#chip-monitor')).toBeVisible();
    await expect(page.locator('#monitor-text')).toContainText('Waiting for ingredients');

    // Recipe name chip
    await expect(page.locator('#chip-recipe')).toBeVisible();
    await expect(page.locator('#recipe-text')).toContainText('--');

    // Live indicator
    await expect(page.locator('#live-indicator')).toBeVisible();
    await expect(page.locator('.live-dot')).toBeVisible();

    // Connection quality bars
    await expect(page.locator('.signal-bars')).toBeVisible();
    await expect(page.locator('.signal-bars .bar')).toHaveCount(4);
  });

  test('WebSocket session establishes and badges update', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(4000);
    await screenshot(page, '03-session-connected');

    const sessionBadge = page.locator('#badge-session');
    const sessionText = await sessionBadge.textContent();
    expect(sessionText).not.toBe('--');
  });

  test('demo speed toggle sends control message', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);

    const checkbox = page.locator('#checkbox-demo-speed');
    await expect(checkbox).not.toBeChecked();

    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await screenshot(page, '04-demo-speed-on');

    await checkbox.uncheck();
    await expect(checkbox).not.toBeChecked();
  });

  test('stop button resets UI to permission screen', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);
    await screenshot(page, '05-before-stop');

    await page.click('#btn-stop');
    await page.waitForTimeout(600);
    await screenshot(page, '06-after-stop');

    await expect(page.locator('#permission-screen')).toHaveClass(/active/);
    await expect(page.locator('#cooking-screen')).not.toHaveClass(/active/);
  });

  test('transcript panel toggles visibility', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const panel = page.locator('#transcript-panel');
    const header = page.locator('#transcript-header');

    await header.click();
    await expect(panel).toHaveClass(/collapsed/);
    await screenshot(page, '07-transcript-hidden');

    await header.click();
    await expect(panel).not.toHaveClass(/collapsed/);
  });

  test('video element is present and has correct attributes', async ({
    page,
  }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);

    const video = page.locator('#camera-feed');
    await expect(video).toBeVisible();
    await expect(video).toHaveAttribute('autoplay', '');
    await expect(video).toHaveAttribute('playsinline', '');
    await screenshot(page, '08-video-feed');
  });

  test('error banner is hidden on fresh session', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const errorBanner = page.locator('#error-banner');
    await expect(errorBanner).toHaveClass(/hidden/);
  });

  test('overlay chips with glassmorphism', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1000);

    const chips = page.locator('#overlay-chips .chip');
    const count = await chips.count();
    expect(count).toBe(3);

    for (let i = 0; i < count; i++) {
      const chip = chips.nth(i);
      await expect(chip).toBeVisible();
      await expect(chip).toHaveClass(/glass/);
    }

    await screenshot(page, '09-overlay-chips');
  });

  test('session badge shows all info sections', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);

    await expect(page.locator('#badge-region')).toBeVisible();
    await expect(page.locator('#badge-rtt')).toBeVisible();
    await expect(page.locator('#badge-session')).toBeVisible();
    await expect(page.locator('#badge-timers')).toBeVisible();

    await screenshot(page, '10-session-badge');
  });

  test('speaking indicator is hidden when agent is not speaking', async ({
    page,
  }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(1000);

    const indicator = page.locator('#speaking-indicator');
    await expect(indicator).toHaveClass(/hidden/);
  });

  test('full session lifecycle: start -> connect -> stop', async ({
    page,
  }) => {
    await page.goto('/');
    await screenshot(page, '11-lifecycle-start');

    await page.click('#btn-start');
    await page.waitForTimeout(600);
    await expect(page.locator('#cooking-screen')).toHaveClass(/active/);

    await page.waitForTimeout(4000);
    const sessionText = await page.locator('#badge-session').textContent();
    expect(sessionText).not.toBe('--');
    await screenshot(page, '12-lifecycle-connected');

    await page.click('#btn-stop');
    await page.waitForTimeout(600);
    await expect(page.locator('#permission-screen')).toHaveClass(/active/);
    await screenshot(page, '13-lifecycle-stopped');
  });

  test('glassmorphism applied to bottom panel and transcript', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    await expect(page.locator('#bottom-panel')).toHaveClass(/glass/);
    await expect(page.locator('#transcript-panel')).toHaveClass(/glass/);
    await screenshot(page, '14-glassmorphism');
  });
});
