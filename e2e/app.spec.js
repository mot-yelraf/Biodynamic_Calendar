// @ts-check
import { test, expect } from '@playwright/test';

test('loads the local app shell and opens Settings without browser errors', async ({ page }) => {
  const browserErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));

  // The Python test suite covers calendar calculations and API payloads. Keep
  // this host-side browser check deterministic by isolating it from ephemeris
  // downloads while still loading the real FastAPI page, CSS, and JavaScript.
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/calendar') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, reason: 'Playwright smoke fixture', calendar: [], plantings: [] }),
      });
      return;
    }
    if (url.pathname === '/api/calendar-range') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, reason: 'Playwright smoke fixture', months: [] }),
      });
      return;
    }
    await route.continue();
  });

  const response = await page.goto('/');
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveTitle(/Biodynamic Calendar/);
  await expect(page.getByRole('heading', { name: /Biodynamic Calendar/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Lunar Calendar' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Lunar Calendar view mode' })).toBeVisible();
  await expect(page.getByText('Observer-local phase timeline')).toBeVisible();
  await expect(page.getByRole('img', { name: 'Sun and Moon events from sunrise to the next sunrise' })).toBeVisible();

  await page.getByRole('button', { name: 'Open Settings' }).click();
  await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Location' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', { name: 'Close Settings' }).click();
  await expect(page.getByRole('dialog', { name: 'Settings' })).not.toBeVisible();

  expect(browserErrors).toEqual([]);
});
