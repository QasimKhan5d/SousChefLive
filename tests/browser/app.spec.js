import { test, expect } from '@playwright/test';

test.describe('SousChef Live — Deployed App', () => {
  test('landing page loads with correct title and elements', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/SousChef/i);

    const heading = page.locator('h1');
    await expect(heading).toContainText('SousChef Live');

    const subtitle = page.locator('.tagline');
    await expect(subtitle).toContainText('real-time AI sous-chef');

    const startBtn = page.locator('#btn-start');
    await expect(startBtn).toBeVisible();
    await expect(startBtn).toContainText('Start Cooking');
  });

  test('landing page has feature badges', async ({ page }) => {
    await page.goto('/');
    const badges = page.locator('.feature-badge');
    await expect(badges).toHaveCount(3);
    await expect(badges.nth(0)).toContainText('Real-time Voice');
    await expect(badges.nth(1)).toContainText('Live Vision');
    await expect(badges.nth(2)).toContainText('Smart Timers');
  });

  test('landing page has powered-by badge', async ({ page }) => {
    await page.goto('/');
    const powered = page.locator('.powered-by');
    await expect(powered).toContainText('Gemini Live API');
  });

  test('health endpoint returns ok', async ({ request }) => {
    const resp = await request.get('/api/health');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.status).toBe('ok');
    expect(body.model).toContain('gemini');
  });

  test('clicking Start transitions to cooking screen', async ({ page }) => {
    await page.goto('/');

    const permScreen = page.locator('#permission-screen');
    const cookScreen = page.locator('#cooking-screen');

    await expect(permScreen).toHaveClass(/active/);
    await expect(cookScreen).not.toHaveClass(/active/);

    await page.click('#btn-start');
    await page.waitForTimeout(600);

    await expect(permScreen).not.toHaveClass(/active/);
    await expect(cookScreen).toHaveClass(/active/);
  });

  test('cooking screen has all required UI elements', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    await expect(page.locator('#recipe-text')).toContainText('--');
    await expect(page.locator('#badge-region')).toContainText('us-central1');
    await expect(page.locator('#badge-rtt')).toBeVisible();
    await expect(page.locator('#badge-session')).toBeVisible();
    await expect(page.locator('#step-text')).toContainText('Idle');
    await expect(page.locator('#monitor-text')).toContainText('Waiting for ingredients');
    await expect(page.locator('#badge-timers')).toBeVisible();
    await expect(page.locator('#timer-area')).toBeAttached();
    await expect(page.locator('#btn-stop')).toBeVisible();
    await expect(page.locator('#checkbox-demo-speed')).toBeVisible();
    await expect(page.locator('#transcript-body')).toBeVisible();
  });

  test('cooking screen has live indicator', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const indicator = page.locator('#live-indicator');
    await expect(indicator).toBeVisible();
    await expect(indicator).toContainText('LIVE');
    await expect(page.locator('.live-dot')).toBeVisible();
  });

  test('cooking screen has connection quality bars', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const bars = page.locator('.signal-bars');
    await expect(bars).toBeVisible();
    await expect(page.locator('.signal-bars .bar')).toHaveCount(4);
  });

  test('WebSocket connects and receives session events', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(3000);

    const sessionText = await page.locator('#badge-session').textContent();
    expect(sessionText).not.toBe('--');
  });

  test('stop button returns to permission screen', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(2000);

    await page.click('#btn-stop');
    await page.waitForTimeout(600);

    const permScreen = page.locator('#permission-screen');
    await expect(permScreen).toHaveClass(/active/);
  });

  test('demo speed checkbox is functional', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const checkbox = page.locator('#checkbox-demo-speed');
    await expect(checkbox).not.toBeChecked();

    await checkbox.check();
    await expect(checkbox).toBeChecked();

    await checkbox.uncheck();
    await expect(checkbox).not.toBeChecked();
  });

  test('error banner is initially hidden', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const errorBanner = page.locator('#error-banner');
    await expect(errorBanner).toHaveClass(/hidden/);
  });

  test('transcript toggle works', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-start');
    await page.waitForTimeout(600);

    const panel = page.locator('#transcript-panel');
    const header = page.locator('#transcript-header');

    await header.click();
    await expect(panel).toHaveClass(/collapsed/);

    await header.click();
    await expect(panel).not.toHaveClass(/collapsed/);
  });
});
