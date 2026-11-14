import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(new URL('../../ticket-editor/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:390,height:900},locale:'ru-RU'});
try{
  await context.addInitScript(()=>localStorage.setItem('codoc:language','ru'));
  const page=await context.newPage();
  await page.goto('https://www.codoc.site/start/tours',{waitUntil:'domcontentloaded'});
  const stop=page.locator('.route-stops > li').nth(1);
  await stop.getByRole('combobox',{name:'Адрес',exact:true}).fill('Площадь Восстания Санкт-Петербург');
  const option=page.getByRole('option').filter({hasText:'Санкт-Петербург'}).first();
  const address=await option.textContent({timeout:45000});await option.getByRole('button').click();
  const panel=stop.locator('.route-place-panel');await panel.locator(':scope > summary').click();
  await panel.getByLabel('Тема прогулки',{exact:true}).selectOption('bars');
  const responsePromise=page.waitForResponse(response=>response.url().includes('/places/themed?'),{timeout:45000});
  await panel.getByRole('button',{name:'Составить карту прогулки',exact:true}).click();
  const response=await responsePromise;const body=await response.json();
  console.log(JSON.stringify({address,status:response.status(),request:new URL(response.url()).search,count:body.places?.length,body}));
  if(body.places?.length)await panel.locator('.route-place-results a').first().waitFor({timeout:15000});
  const report={address,status:response.status(),request:new URL(response.url()).search,count:body.places?.length,labels:await panel.locator('.route-place-results > li > a').allTextContents(),alerts:await panel.getByRole('alert').allTextContents()};
  await panel.screenshot({path:'reports/live-bars-vosstaniya.png'});
  await panel.locator(':scope > summary').click();
  await writeFile('reports/live-bars-vosstaniya.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  if(!report.count)throw new Error('No bars returned near Vosstaniya');
}finally{await context.close();await browser.close();}
