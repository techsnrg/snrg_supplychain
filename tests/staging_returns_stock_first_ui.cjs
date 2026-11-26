// Uses OS-keyring credential supplied over stdin; tests only loopback Docker staging.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),assert=require('assert');
(async()=>{
 let input='';for await(const x of process.stdin)input+=x;const secret=JSON.parse(input);input='';
 const result=JSON.parse(fs.readFileSync('staging/results-returns-stock-first.json','utf8'));
 const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000}}),base='http://127.0.0.1:18081';
 const login=await context.request.post(base+'/api/method/login',{form:{usr:secret.user||'Administrator',pwd:secret.password}});secret.password='';if(login.status()!==200){await browser.close();throw new Error('Staging UI authentication failed: '+login.status());}
 const page=await context.newPage(),errors=[],assets=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&/\.(css|js)(\?|$)/.test(r.url()))assets.push({url:r.url(),status:r.status()});});
 async function form(dt,name){await page.goto(base+'/desk/'+dt.toLowerCase().replaceAll(' ','-')+'/'+name);await page.waitForFunction(({dt,name})=>window.cur_frm&&cur_frm.doctype===dt&&cur_frm.doc.name===name&&!frappe.dom.freeze_count,{dt,name},{timeout:45000});await page.evaluate(()=>new Promise(r=>frappe.after_ajax(r)));}
 try{
  const r=result.records;
  for(const [dt,name] of [['Material Return Authorization',r.credit_mra],[r.arrival_type,r.arrival],['Delivery Note',r.delivery_arrival],['Purchase Receipt',r.purchase_arrival],['Quality Inspection',r.qi],['Sales Invoice',r.credit_note],['Purchase Invoice',r.purchase_invoice]]){
   await form(dt,name);await page.locator('.form-layout').first().waitFor();
   await page.screenshot({path:'inspection/stock-first-'+dt.toLowerCase().replaceAll(' ','-')+'-desktop.png',fullPage:true});
   await page.setViewportSize({width:390,height:844});await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.cur_frm&&!frappe.dom.freeze_count);await page.evaluate(()=>new Promise(r=>frappe.after_ajax(r)));await page.screenshot({path:'inspection/stock-first-'+dt.toLowerCase().replaceAll(' ','-')+'-mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});
   checks.push(dt+' loads on desktop and mobile');
  }
  await form(r.arrival_type,r.arrival);
  assert(await page.getByRole('button',{name:'Inspect arrived material',exact:true}).isVisible());
  assert(await page.getByRole('button',{name:'Move inspected stock',exact:true}).isVisible());
  checks.push('Native arrival exposes inspection and QC stock disposition actions');
  await page.evaluate(async({quarantine,invoiceName})=>{
   const response=await frappe.call({method:'frappe.client.get',args:{doctype:'Sales Invoice',name:invoiceName}});const invoice=response.message;
   await frappe.new_doc('Material Return Authorization');
   await cur_frm.set_value({company:invoice.company,customer:invoice.customer,currency:invoice.currency,return_warehouse:quarantine,responsible_user:frappe.session.user,information_complete:1,freight_terms:'Browser stock-first QA'});
   cur_frm.clear_table('items');const source=invoice.items[0];const row=cur_frm.add_child('items',{item_code:source.item_code,uom:source.uom,claimed_category:'Suspected Manufacturing Defect',claimed_qty:1,approved_qty:1,condition:'Current Saleable',reason:'Browser stock-first QA',sales_invoice:invoice.name,sales_invoice_item:source.name,invoice_source:'Manually Selected',invoice_confirmed:1});cur_frm.refresh_field('items');await cur_frm.save();
  },{quarantine:r.quarantine,invoiceName:r.original_sale});
  async function action(name,state){await page.locator('.actions-btn-group:visible button').click();await page.getByText(name,{exact:true}).last().click();await page.getByRole('dialog').getByRole('button',{name:'Yes',exact:true}).click();await page.waitForFunction(s=>cur_frm.doc.workflow_state===s,state);}
  await action('Request Approval','Pending Approval');await page.evaluate(async()=>{await cur_frm.set_value('approval_reason','Stock-first browser authorization');await cur_frm.save();});await action('Authorize','Authorized');
  assert.equal(await page.getByRole('button',{name:'Record custody receipt',exact:true}).count(),0);
  await page.getByRole('button',{name:'Receive into Returns warehouse',exact:true}).click();let dialog=page.getByRole('dialog');await dialog.waitFor();await dialog.locator('select[data-fieldname="choice"]').selectOption('0');await dialog.getByRole('button',{name:'Create draft',exact:true}).click();
  await page.waitForFunction(()=>cur_frm.doctype==='Stock Entry'&&cur_frm.is_new()&&cur_frm.doc.custom_return_purpose==='Arrival'&&cur_frm.doc.items.length>0);
  assert.equal(await page.evaluate(()=>cur_frm.doc.items[0].t_warehouse),r.quarantine);
  checks.push('Native Workflow authorizes v3 MRA and creates stock arrival draft directly into quarantine');
  assert.deepEqual(errors.filter(x=>!x.includes('socket.io')),[]);assert.deepEqual(assets,[]);
  const output={passed:true,checks,errors:[],assetErrors:assets};fs.writeFileSync('staging/results-returns-stock-first-browser.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output));
 }catch(e){console.error(JSON.stringify({url:page.url(),errors,assets,body:(await page.locator('body').innerText()).slice(-2000)}));await page.screenshot({path:'inspection/stock-first-browser-failure.png',fullPage:true});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
