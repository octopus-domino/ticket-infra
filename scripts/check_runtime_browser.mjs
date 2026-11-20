import assert from 'node:assert/strict';
import { parseArgs } from 'node:util';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

// Resolve Playwright from the checked-out frontend; no machine-specific imports or saved profile.
const { values } = parseArgs({ options: {
  'frontend-root': { type: 'string' }, 'base-url': { type: 'string' },
  map: { type: 'boolean', default: false }, screenshot: { type: 'string' },
  handoff: { type: 'boolean', default: false }, channel: { type: 'string' },
} });
if (!values['frontend-root'] || !values['base-url']) {
  throw new Error('Required: --frontend-root <private_jorney> --base-url <https://your-site>');
}
const require = createRequire(resolve(values['frontend-root'], 'package.json'));
const { chromium } = require('@playwright/test');
const browser = await chromium.launch({ headless: true, channel: values.channel });
const base = values['base-url'].replace(/\/+$/, '');
try {
  const page = await browser.newPage({ viewport: { width: 393, height: 851 }, isMobile: true, hasTouch: true });
  const requests = [], failures = [];
  page.on('request', request => { if (request.url().includes('/api/')) requests.push(new URL(request.url()).pathname); });
  page.on('requestfailed', request => { if (request.url().includes('/api/')) failures.push(new URL(request.url()).pathname); });
  page.on('pageerror', error => failures.push(error.message));
  await page.goto(base + '/app', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  console.log(JSON.stringify({ component: 'editor', requests: [...requests], failures: [...failures] }));
  requests.length = 0; failures.length = 0;
  if (values.map) {
    // Synthetic test record is written only into this disposable browser context.
    await page.addInitScript(() => localStorage.setItem('private-walks/browser-recording/v1', JSON.stringify({
      id: 'release-map-check', startedAt: Date.now() - 60000, endedAt: Date.now(), state: 'stopped', pointCount: 1, distanceMeters: 0,
      points: [{ lat: 59.94, lng: 30.27, accuracy: 8, timestamp: Date.now() - 60000 }],
    })));
  }
  await page.goto(base + '/private-journey/', { waitUntil: 'domcontentloaded' });
  if (values.map) {
    const open = async () => {
      await page.getByRole('button', { name: 'Записать прогулку', exact: true }).click();
      await page.locator('.recording-list__open').click();
      await page.waitForFunction(() => {
        const node = document.querySelector('.walk-report-map__canvas');
        return node && getComputedStyle(node).opacity === '1';
      }, undefined, { timeout: 30000 });
    };
    await open();
    await page.route('https://tile.openstreetmap.org/**', route => route.abort());
    await page.reload({ waitUntil: 'domcontentloaded' });
    await open();
    console.log('Recorded map: visible online and from the tile cache with network blocked');
  }
  if (values.screenshot) await page.screenshot({ path: values.screenshot });
  console.log(JSON.stringify({ component: 'private-journey', requests, failures }));
  if (failures.length) throw new Error('Browser runtime failures detected');
  if (values.handoff) await checkHandoff(browser, base);
} finally { await browser.close(); }

async function checkHandoff(browser, base) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, locale: 'en-US' });
  try {
    const first = { id: 'first', name: 'Первая точка', lat: 59.94, lng: 30.27, source: 'manual',
      categoryIds: ['historical-house'], facts: [], details: {} };
    const second = { ...first, id: 'second', name: 'Вторая точка', lng: 30.29 };
    const geometry = [[first.lat, first.lng], [second.lat, second.lng]];
    const route = { geometry, legs: [{ fromIndex: 0, toIndex: 1, geometry, distanceMeters: 1200, durationSeconds: 900 }],
      totalDistanceMeters: 1200, totalDurationSeconds: 900 };
    const now = new Date().toISOString();
    const draft = { id: 'release-walk', title: 'Проверка передачи', createdAt: now, updatedAt: now,
      area: { anchors: [], radiusMeters: 800 }, selectedCategoryIds: [], selectedPoiIds: ['first', 'second'],
      view: 'map', savedPois: [first, second], savedRoute: route, savedFailedSegments: [] };
    await page.addInitScript(value => {
      localStorage.setItem('codoc:language', 'en');
      if (location.pathname !== '/private-journey/') return;
      localStorage.setItem('private-walks/drafts/v1', JSON.stringify([value]));
      const url = new URL(location.href);
      url.searchParams.set('draft', value.id);
      history.replaceState(null, '', url);
    }, draft);

    await page.goto(base + '/start/tours', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Travel planner', exact: true }).click();
    const planner = page.getByRole('region', { name: 'Travel planner' });
    const future = days => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);
    await planner.getByLabel('Start date').fill(future(7));
    await planner.getByLabel('End date').fill(future(8));
    await planner.getByRole('button', { name: 'Next day' }).click();
    await planner.getByRole('button', { name: 'Plan walk in Journey' }).click();
    const frame = page.frameLocator('iframe[src^="/private-journey/"]');
    const title = frame.getByRole('textbox', { name: 'Название прогулки' });
    assert.equal(await title.inputValue(), draft.title);
    const routePanel = frame.getByRole('button', { name: /📍 Маршрут/ });
    if (await routePanel.isVisible()) await routePanel.click();
    await frame.getByRole('button', { name: 'Включить в общий маршрут' }).click();
    await frame.getByRole('button', { name: 'Добавить в путешествие CoDoc' }).click();
    await planner.getByRole('button', { name: 'Use this walk' }).click();
    const day = () => page.evaluate(() => JSON.parse(localStorage.getItem('codoc/trip-planner/draft/v2')).days['2']);
    assert.deepEqual((await day()).importedWalk.legs[0].coordinates, [[first.lng, first.lat], [second.lng, second.lat]]);
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.equal((await day()).stops.length, 2);
    console.log(JSON.stringify({ check: 'journey-handoff', day: 2, stops: 2, viewport: [390, 844], storedAfterReload: true }));
  } finally { await page.close(); }
}
