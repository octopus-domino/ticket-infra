import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../../ticket-editor/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
  for(const [kind,width] of [['document',1440],['template',390]]){
    const context=await browser.newContext({viewport:{width,height:900},hasTouch:width===390,isMobile:width===390});
    await context.addInitScript(kind=>{
      localStorage.setItem('codoc:language','en');sessionStorage.setItem('codoc:guest','1');
      if(sessionStorage.getItem('codoc:guest:resources'))return;
      const page={id:'page',name:'Release check',width:794,height:1123,format:'a4',orientation:'portrait',padding:{top:20,right:20,bottom:20,left:20},background:'#ffffff',elements:[]};
      const record={id:'release-background-check',name:'Release verification',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),folderId:null};
      const resources=kind==='document'?{document:[{...record,content:JSON.stringify({version:'2.0',slides:[page],activeId:'page',data:[]})}]}:{template:[{...record,schemaId:null,slides:[page],bindings:[],fields:[]}]};
      sessionStorage.setItem('codoc:guest:resources',JSON.stringify(resources));
    },kind);
    const page=await context.newPage();page.setDefaultTimeout(30000);
    await page.goto(`https://www.codoc.site${kind==='document'?'/app/editor/release-background-check':'/app/templates/release-background-check/edit'}`);
    const canvas=page.locator('.konvajs-content canvas').first();await expect(canvas).toBeVisible();
    const fingerprint=()=>canvas.evaluate(canvas=>{
      const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
      let hash=0;for(let i=0;i<pixels.length;i+=101)hash=(hash*31+pixels[i])|0;return hash;
    });
    const before=await fingerprint();
    await page.getByRole('button',{name:'Tool library',exact:true}).click();
    await page.locator('.section-head').filter({hasText:'Images'}).click();
    const library=page.locator('.background-library');await library.locator('summary').click();
    await library.getByRole('button',{name:'Sage paper',exact:true}).click();
    await expect.poll(fingerprint).not.toBe(before);
    await page.screenshot({path:fileURLToPath(new URL(`../reports/live-editor-background-${kind}.png`,import.meta.url)),fullPage:true});
    console.log(`PASS live ${kind} at ${width}px: background changes actual canvas pixels; guest content stays local.`);
    await context.close();
  }
}finally{await browser.close();}
