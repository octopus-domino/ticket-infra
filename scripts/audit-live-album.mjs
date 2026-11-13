import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../ticket-editor/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
const page = await context.newPage();
await page.addInitScript(() => localStorage.setItem('codoc:language', 'en'));
let issued;
try {
  await page.goto('https://www.codoc.site/start/albums');
  await page.getByRole('textbox', { name: /^title$/i }).fill('CoDoc release verification');
  await page.locator('.background-library summary').click();
  const background = page.waitForResponse(response => new URL(response.url()).pathname === '/api/journeys/media/background' && response.request().method() === 'POST');
  await page.locator('.background-library-grid button').first().click();
  const selected = await background;
  if (!selected.ok()) throw new Error(`Background upload HTTP ${selected.status()}`);
  const creation = page.waitForResponse(response => new URL(response.url()).pathname === '/api/journeys' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  const response = await creation;
  if (!response.ok()) throw new Error(`Album creation HTTP ${response.status()}`);
  [issued] = await response.json();
  await page.getByLabel('Photo caption', { exact: true }).fill('Проверка фотографии и подписи');
  const photo = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/album/photos') && response.request().method() === 'POST');
  await page.getByLabel('Add photos', { exact: true }).setInputFiles(fileURLToPath(new URL('../../ticket-editor/public/backgrounds/thumbs/sage-paper.jpg', import.meta.url)));
  const uploaded = await photo;
  if (!uploaded.ok()) throw new Error(`Photo upload HTTP ${uploaded.status()}`);
  await page.locator('.album-photos > li').first().waitFor();
  const pdf = await context.request.get(`https://www.codoc.site/api/journeys/${issued.document.id}/pdf`, { timeout: 90000 });
  if (!pdf.ok() || !(await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF'))) throw new Error(`PDF HTTP ${pdf.status()}`);
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Horizontal overflow');
  await page.screenshot({path:fileURLToPath(new URL('../reports/live-album-background.png',import.meta.url)),fullPage:true});
  console.log('PASS live mobile album: background, creation, photograph, Cyrillic caption and native PDF');
} finally {
  if (issued) {
    const cleanup = await context.request.post(`https://www.codoc.site/api/journeys/${issued.document.id}/status`, {
      headers: {'X-Management-Key':issued.managementKey}, data:{action:'REVOKE'},
    });
    console.log(`Synthetic album revoked: ${cleanup.status()}`);
  }
  await browser.close();
}
