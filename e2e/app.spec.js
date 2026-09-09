// @ts-check
import { test, expect } from '@playwright/test';

function successfulMonth(monthKey = '2026-09') {
  const [year, month] = monthKey.split('-').map(Number);
  const monthStart = new Date(Date.UTC(year, month - 1, 1));
  const gridStart = new Date(monthStart);
  gridStart.setUTCDate(1 - monthStart.getUTCDay());
  const calendar = Array.from({ length: 42 }, (_, offset) => {
    const current = new Date(gridStart);
    current.setUTCDate(gridStart.getUTCDate() + offset);
    const date = current.toISOString().slice(0, 10);
    return {
      date,
      day: current.getUTCDate(),
      in_month: current.getUTCMonth() === month - 1,
      is_today: date === `${monthKey}-15`,
      dominant_sign: 'Taurus',
      dominant_sign_abbr: 'Tau',
      dominant_element: 'Earth',
      dominant_plant_part: 'Root',
      dominant_color: '#e5b172',
      dominant_accent: '#644817',
      moon_direction: 'ascending',
      segments: [{ start: '00:00', end: '24:00', sign: 'Taurus', plant_part: 'Root' }],
      lunar_events: [],
    };
  });
  return {
    ok: true,
    month_label: monthStart.toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }),
    weekday_labels: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    current: { sign: 'Taurus', element: 'Earth', plant_part: 'Root', window_start_hm: '00:00', window_end_hm: '24:00' },
    calendar,
    notes: {},
    plantings: [],
    astro: { ok: false, reason: 'Browser fixture' },
    location: { ok: true, latitude: 39.7392, longitude: -104.9903, timezone_name: 'America/Denver' },
  };
}

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
  const manifestHref = await page.locator('link[rel="manifest"]').getAttribute('href');
  const manifestResponse = await page.request.get(manifestHref);
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = await manifestResponse.json();
  expect(manifest.name).toBe('Biodynamic Calendar');
  const iconSize = await page.evaluate(async (src) => {
    const icon = new Image();
    icon.src = src;
    await icon.decode();
    return [icon.naturalWidth, icon.naturalHeight];
  }, manifest.icons[0].src);
  expect(iconSize).toEqual([512, 512]);
  await expect(page).toHaveTitle(/Biodynamic Calendar/);
  await expect(page.getByRole('heading', { name: /Biodynamic Calendar/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Lunar Calendar' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Lunar Calendar view mode' })).toBeVisible();
  await expect(page.getByText('Observer-local phase timeline')).toBeVisible();
  await expect(page.getByRole('img', { name: 'Sun and Moon events from sunrise to the next sunrise' })).toBeVisible();

  await page.getByRole('button', { name: 'Open Settings' }).click();
  await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Location' })).toHaveAttribute('aria-selected', 'true');
  const dialog = page.getByRole('dialog', { name: 'Settings' });
  await expect(dialog.locator('footer')).toHaveCount(0);
  await expect(dialog.locator('[data-close-settings]')).toHaveCount(1);
  await expect(dialog).toHaveCSS('border-radius', '18px');
  const logo = dialog.getByRole('img', { name: 'Peace Hill Studios' });
  await expect(logo).toBeVisible();
  expect(await logo.evaluate((image) => image.complete && image.naturalWidth > 0)).toBeTruthy();
  await expect(dialog.locator('#status')).toBeVisible();
  for (const theme of ['spring', 'summer', 'autumn', 'winter']) {
    await page.evaluate((theme) => {
      document.body.className = `theme-${theme}`;
    }, theme);
    const paletteColor = await page.locator('body').evaluate((body) => {
      const probe = document.createElement('span');
      probe.style.backgroundColor = 'var(--theme-panel-soft)';
      body.append(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return color;
    });
    await expect(dialog.locator('.settings-modal-header')).toHaveCSS('background-color', paletteColor);
  }
  await page.getByRole('tab', { name: 'Appearance', exact: true }).click();
  const appearancePane = dialog.locator('[data-pane="appearance"]');
  for (const viewport of [{ width: 1280, height: 900 }, { width: 1440, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await expect(appearancePane).toBeVisible();
    expect(await appearancePane.evaluate((pane) => pane.scrollHeight <= pane.clientHeight)).toBeTruthy();
    await expect(dialog.getByRole('button', { name: 'Save Appearance', exact: true })).toBeInViewport();
    const bottomGap = await appearancePane.evaluate((pane) => {
      const actions = pane.querySelector('.settings-pane-actions');
      return pane.getBoundingClientRect().bottom - actions.getBoundingClientRect().bottom;
    });
    expect(bottomGap).toBeGreaterThanOrEqual(20);
    expect(bottomGap).toBeLessThanOrEqual(56);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(logo).toBeInViewport();
  await page.getByRole('tab', { name: 'Appearance', exact: true }).click();
  await expect(dialog.locator('[data-pane="appearance"]')).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy();
  await page.getByRole('button', { name: 'Close Settings' }).click();
  await expect(page.getByRole('dialog', { name: 'Settings' })).not.toBeVisible();

  expect(browserErrors).toEqual([]);
});

test('renders a successful month and exercises navigation, notes, and plantings', async ({ page }) => {
  const noteWrites = [];
  const plantingWrites = [];
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/calendar') {
      const month = url.searchParams.get('month') || '2026-09';
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(successfulMonth(month)) });
      return;
    }
    if (url.pathname === '/api/calendar-range') {
      const start = url.searchParams.get('start') || '2026-09';
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, months: [successfulMonth(start)] }) });
      return;
    }
    if (url.pathname === '/api/daily-summary') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, summary: 'Biodynamic Hints\nSuggestion: tend roots.' }) });
      return;
    }
    if (url.pathname === '/api/note' && request.method() === 'POST') {
      noteWrites.push(request.postDataJSON());
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) });
      return;
    }
    if (url.pathname === '/api/planting' && request.method() === 'POST') {
      const planting = { id: 'lettuce', ...request.postDataJSON() };
      plantingWrites.push(planting);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, planting, plantings: [planting] }) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.locator('#calendar .bio-day')).toHaveCount(42);
  await expect(page.locator('#monthLabel')).toHaveText('September 2026');
  await page.locator('#calendar [data-date="2026-09-15"]').click();
  await expect(page.locator('#dailySummary')).toContainText('tend roots');

  await page.locator('.inspector-section').filter({ hasText: 'Note' }).locator('summary').click();
  await page.locator('#noteInput').fill('Watered the root bed.');
  await page.getByRole('button', { name: 'Save Note' }).click();
  await expect.poll(() => noteWrites.length).toBe(1);
  expect(noteWrites[0]).toEqual({ date: '2026-09-15', note: 'Watered the root bed.' });

  await page.locator('.planting-panel > summary').click();
  await page.locator('#plantingEditor > summary').click();
  await page.locator('#plantingForm [name="name"]').fill('Lettuce');
  await page.locator('#plantingForm [name="start_date"]').fill('2026-09-15');
  await page.getByRole('button', { name: 'Save Planting' }).click();
  await expect.poll(() => plantingWrites.length).toBe(1);
  expect(plantingWrites[0].name).toBe('Lettuce');

  await page.getByRole('button', { name: '→' }).click();
  await expect(page.locator('#monthLabel')).toHaveText('October 2026');
});
