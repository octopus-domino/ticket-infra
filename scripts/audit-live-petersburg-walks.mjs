import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(new URL('../../ticket-editor/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[];
try{
  for(const width of [390,1440]){
    const context=await browser.newContext({viewport:{width,height:900},locale:'ru-RU',isMobile:width===390,hasTouch:width===390});
    await context.addInitScript(()=>localStorage.setItem('codoc:language','ru'));
    const page=await context.newPage();
    await page.goto('https://www.codoc.site/start/tours',{waitUntil:'domcontentloaded',timeout:60000});
    const stops=page.locator('.route-stops > li');
    await stops.nth(1).getByRole('combobox',{name:'Адрес',exact:true}).fill('Санкт-Петербург');
    await page.getByRole('option').filter({hasText:'Санкт-Петербург'}).first().getByRole('button').click({timeout:45000});
    const panel=stops.nth(1).locator('.route-place-panel');
    await panel.locator(':scope > summary').click();
    await panel.locator('.route-ready-walks > summary').click();
    const titles=await panel.locator('.route-ready-walks h4').allTextContents();
    const item={width,titles,withinViewport:await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)};
    if(titles.length!==3||!item.withinViewport)throw new Error('Ready-walk gallery is incomplete or overflows');
    await panel.screenshot({path:`reports/live-petersburg-walks-${width}.png`});
    if(width===390&&process.env.VERIFY_WALK_GENERATION==='true'){
      await panel.locator('.route-ready-walks button').first().click();
      await panel.locator('.route-walk-print').waitFor({timeout:150000});
      item.generated=true;
      item.walkTitle=await panel.locator('.route-walk h4').textContent();
      item.mainStops=await stops.count();
      item.timeline=await panel.locator('.route-walk .route-timeline strong').allTextContents();
      await panel.locator('.route-walk').screenshot({path:'reports/live-petersburg-generated.png'});
    }
    results.push(item);await context.close();
  }
}finally{await browser.close();}
await writeFile('reports/live-petersburg-walks.json',JSON.stringify(results,null,2));
console.log(JSON.stringify(results));
