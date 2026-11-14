import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(new URL('../../ticket-editor/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[];
try {
  for(const width of [390,1440]){
    const context=await browser.newContext({viewport:{width,height:900},locale:'ru-RU',hasTouch:width===390,isMobile:width===390});
    await context.addInitScript(()=>localStorage.setItem('codoc:language','ru'));
    const page=await context.newPage();const violations=[];
    page.on('console',message=>{
      const text=message.text();
      if(/content security policy|unsafe-eval|Refused to/i.test(text))violations.push(text.replace(/apikey=[^&\s"']+/g,'apikey=[redacted]').slice(0,350));
    });
    await page.goto('https://www.codoc.site/start/tours',{waitUntil:'domcontentloaded',timeout:60000});
    await page.locator('.route-map-picker .route-yandex-map select').selectOption('yandex',{timeout:30000});
    let loaded=true;
    try{await page.frameLocator('.route-map-picker iframe').locator('[class*="-map"]').first().waitFor({timeout:45000});}catch{loaded=false;}
    results.push({width,loaded,withinViewport:await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),violations});
    await page.screenshot({path:`reports/live-yandex-${width}.png`,fullPage:true});await context.close();
  }
}finally{await browser.close();}
await writeFile('reports/live-yandex-map.json',JSON.stringify(results,null,2));
console.log(JSON.stringify(results));
if(results.some(result=>!result.loaded||!result.withinViewport))process.exitCode=1;
