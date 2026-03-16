import { test, expect } from '@playwright/test';

test.describe('Proactive Behavior — Debug Events', () => {
  test('debug API is available and has proactive event types', async ({ page }) => {
    await page.goto('/');
    const hasDebug = await page.evaluate(() => typeof window.__souschef_debug !== 'undefined');
    expect(hasDebug).toBe(true);

    const methods = await page.evaluate(() => Object.keys(window.__souschef_debug));
    expect(methods).toContain('getEventBuffer');
    expect(methods).toContain('getEventsByType');
    expect(methods).toContain('clearEventBuffer');
    expect(methods).toContain('getRunId');
  });

  test('no unsolicited turns on landing page (negative control)', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);

    const unsolicitedStarts = await page.evaluate(
      () => window.__souschef_debug.getEventsByType('unsolicited_turn_started').length
    );
    expect(unsolicitedStarts).toBe(0);

    const bargeIns = await page.evaluate(
      () => window.__souschef_debug.getEventsByType('barge_in_detected').length
    );
    expect(bargeIns).toBe(0);
  });

  test('run_id is received from server after connect', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => window.__souschef_debug.clearEventBuffer());

    const startBtn = page.locator('#btn-start');
    await startBtn.click();

    await expect(page.locator('#badge-session')).not.toContainText('--', { timeout: 15000 });
    await page.waitForTimeout(5000);

    const runIdEvents = await page.evaluate(
      () => window.__souschef_debug.getEventsByType('server_run_id_received')
    );
    expect(runIdEvents.length).toBeGreaterThan(0);
    expect(runIdEvents[0].details.run_id).toMatch(/^run_/);
  });

  test('silent fake-media session produces no unsolicited proactive UI events', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => window.__souschef_debug.clearEventBuffer());
    await page.click('#btn-start');
    await expect(page.locator('#cooking-screen')).toHaveClass(/active/, { timeout: 10000 });
    await page.waitForTimeout(20000);

    const summary = await page.evaluate(() => ({
      proactiveMeta: window.__souschef_debug.getEventsByType('proactive_meta_received'),
      unsolicitedStarts: window.__souschef_debug.getEventsByType('unsolicited_turn_started'),
      unsolicitedCompleted: window.__souschef_debug.getEventsByType('unsolicited_turn_completed'),
      bargeIns: window.__souschef_debug.getEventsByType('barge_in_detected'),
      chefTranscripts: window.__souschef_debug
        .getEventsByType('transcript_updated')
        .filter((e) => e.details?.role === 'chef'),
    }));

    expect(summary.proactiveMeta).toHaveLength(0);
    expect(summary.unsolicitedStarts).toHaveLength(0);
    expect(summary.unsolicitedCompleted).toHaveLength(0);
    expect(summary.bargeIns).toHaveLength(0);
    expect(summary.chefTranscripts).toHaveLength(0);
  });

  test('run_id and proactive debug hooks stay observable during session', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => window.__souschef_debug.clearEventBuffer());
    await page.click('#btn-start');
    await expect(page.locator('#badge-session')).not.toContainText('--', { timeout: 15000 });
    await page.waitForTimeout(8000);

    const snapshot = await page.evaluate(() => ({
      runIdEvents: window.__souschef_debug.getEventsByType('server_run_id_received'),
      wsOpenEvents: window.__souschef_debug.getEventsByType('ws_open'),
      proactiveMetaEvents: window.__souschef_debug.getEventsByType('proactive_meta_received'),
      currentRunId: window.__souschef_debug.getRunId(),
    }));

    expect(snapshot.wsOpenEvents.length).toBeGreaterThan(0);
    expect(snapshot.runIdEvents.length).toBeGreaterThan(0);
    expect(snapshot.runIdEvents[0].details.run_id).toMatch(/^run_/);
    expect(typeof snapshot.currentRunId).toBe('string');
    expect(snapshot.currentRunId.length).toBeGreaterThan(0);
    expect(Array.isArray(snapshot.proactiveMetaEvents)).toBe(true);
  });
});
