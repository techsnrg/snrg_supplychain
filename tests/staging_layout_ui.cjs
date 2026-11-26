const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{
 let input='';for await(const chunk of process.stdin)input+=chunk;const secret=JSON.parse(input);input='';
 const inventory=JSON.parse(fs.readFileSync('staging/layout-inventory.json','utf8'));
 const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000}}),base='http://127.0.0.1:18081';
 const login=await context.request.post(base+'/api/method/login',{form:{usr:secret.user,pwd:secret.password}});secret.password='';if(login.status()!==200){await browser.close();throw Error('Staging login failed');}
 const page=await context.newPage(),errors=[],assets=[],checks=[],measurements=[];page.setDefaultTimeout(20000);
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&/\.(css|js)(\?|$)/.test(r.url()))assets.push({url:r.url(),status:r.status()});});
 const goto=url=>page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
 const settle=()=>page.evaluate(()=>new Promise(resolve=>frappe.after_ajax(resolve)));
 async function width(w){await page.setViewportSize({width:w,height:w<700?900:1000});}
 async function overflow(label){const x=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(x.scroll<=x.width+2,label+': viewport overflow '+JSON.stringify(x));}
 async function loadForm(row){
  if(['Return Inspection','Return Settlement'].includes(row.doctype)){await goto(base+'/desk/Form/'+encodeURIComponent(row.doctype)+'/'+encodeURIComponent(row.name));}
  else {await goto(base+'/desk/supply-chain');await page.waitForFunction(()=>window.frappe?.boot);
  await page.evaluate(async row=>{await frappe.model.with_doctype(row.doctype);if(row.name||row.single)await frappe.set_route('Form',row.doctype,row.name||row.doctype);else await frappe.new_doc(row.doctype);},row);}
  await page.waitForFunction(dt=>window.cur_frm&&cur_frm.doctype===dt&&!frappe.dom.freeze_count,row.doctype,{timeout:45000});await settle();
 }

 try{
  for(const row of inventory.filter(x=>!x.child)){
   await width(1440);await loadForm(row);
   await page.locator('.form-layout').first().waitFor();
   const tabs=await page.evaluate(()=>cur_frm.meta.fields.filter(f=>f.fieldtype==='Tab Break').map(f=>({name:f.fieldname,label:f.label})));
   for(const tab of tabs){
    const button=page.locator('.form-tabs-list').getByText(tab.label,{exact:true});
    if(await button.count()&&await button.first().isVisible())await button.first().click();
    await overflow(row.doctype+' / '+tab.label);
   }
   if(tabs.length){await page.locator('.form-tabs-list').getByText(tabs[0].label,{exact:true}).first().click();}
   for(const w of [1440,768,390,320]){
    await width(w);await overflow(row.doctype+' '+w);
    if(row.doctype==='Material Return Authorization'&&w===1440){
      const layout=await page.evaluate(()=>Object.fromEntries(['company','request_date','responsible_user','items'].map(name=>{const e=cur_frm.fields_dict[name].$wrapper[0],r=e.getBoundingClientRect();return [name,{x:r.x,y:r.y,width:r.width}]})));
      assert(layout.company.x+100<layout.request_date.x&&layout.request_date.x+100<layout.responsible_user.x,'MRA header must use three native columns');
      assert(layout.items.y<850,'MRA item table should be visible without scrolling past a long single-column header');measurements.push(layout);
    }
    if(w===1440||w===390)await page.screenshot({path:'inspection/layout-'+row.doctype.toLowerCase().replaceAll(' ','-')+'-'+w+'.png',fullPage:true});
   }
   checks.push(row.doctype+': tabs and layout at 1440, 768, 390 and 320px');
  }
  await width(1440);
  for(const row of inventory.filter(x=>x.child)){
   await page.evaluate(async dt=>{await frappe.model.with_doctype(dt);const fields=frappe.get_meta(dt).fields.map(x=>({...x}));window.layoutDialog=new frappe.ui.Dialog({title:dt,fields,size:'large'});layoutDialog.show();},row.doctype);
   for(const w of [1440,390,320]){await width(w);await overflow(row.doctype+' child '+w);}
   await page.evaluate(()=>{layoutDialog.hide();layoutDialog=null;});checks.push(row.doctype+': child editor renders and fits narrow screens');
  }
  for(const [route,root] of [['daily-production-entry','.daily-production'],['bulk-disassembly-entry','.bulk-disassembly'],['packing_station','.ps2-app'],['warehouse-home','.ps2-app'],['ready-to-invoice','.snrg-invoice-queue'],['packed_carton_touch','.ps2-app']]){
   await width(1440);await goto(base+'/desk/'+route);await page.locator(root).first().waitFor({timeout:45000});await settle();
   for(const w of [1440,768,390,320]){
    await width(w);await overflow(route+' '+w);
    if(w===1440||w===390)await page.screenshot({path:'inspection/layout-page-'+route+'-'+w+'.png',fullPage:true});
   }
   // Check logical direction and zoom reflow without modifying persisted settings.
   await page.evaluate(()=>document.documentElement.dir='rtl');await overflow(route+' RTL');await page.evaluate(()=>document.documentElement.dir='ltr');
   await width(720);await overflow(route+' 200% equivalent reflow');checks.push(route+': desktop/mobile, RTL and zoom-equivalent reflow');
  }
  assert.deepEqual(errors.filter(x=>!x.includes('socket.io')),[],'Runtime errors');assert.deepEqual(assets,[],'Missing assets');
  const result={passed:true,checks,measurements,errors:[],assetErrors:assets};fs.writeFileSync('staging/results-layout-browser.json',JSON.stringify(result,null,2));console.log(JSON.stringify({passed:true,checks:checks.length}));
 }catch(e){console.error(JSON.stringify({url:page.url(),errors,assets,body:(await page.locator('body').innerText()).slice(-1800)}));await page.screenshot({path:'inspection/layout-failure.png',fullPage:true});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
