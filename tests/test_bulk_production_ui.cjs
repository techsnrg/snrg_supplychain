const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('snrg_supplychain/supply_chain/page/daily_production_entry/daily_production_entry.js','utf8');
const ctx={frappe:{pages:{'daily-production-entry':{}},datetime:{get_today:()=> '2026-11-17'},route_options:null},__:x=>x,clearTimeout,setTimeout,URL,URLSearchParams,window:{location:{protocol:'http:',pathname:'/desk/daily-production-entry',href:'http://localhost/desk/daily-production-entry?sheet=old'},history:{replaceState(){}}}};
vm.createContext(ctx);vm.runInContext(source+'\nglobalThis.Screen=DailyProductionScreen;',ctx);
function screen(){const controls={};const s=Object.create(ctx.Screen.prototype);s.root={find(key){return controls[key] ||= {value:'',content:'',val(v){if(v===undefined)return this.value;this.value=v;return this},text(v){this.content=v;return this},html(v){this.content=v;return this},attr(){return this},prop(){return this},toggle(){return this},toggleClass(){return this}}}};s.doc={name:'DPROD-test',status:'Draft',items:[{item_code:'A',qty:1}]};s.station={get_value:()=> 'Station',$input:{prop(){}}};s.sourceWarehouse={get_value:()=> 'Source',set_value(){},$input:{prop(){}}};s.targetWarehouse={get_value:()=> 'Target',set_value(){},$input:{prop(){}}};s.item={get_value:()=>'',set_value(){}};s.esc=String;s.feedback=(t,e)=>{s.message=t;s.error=e};return s}
(async()=>{
 let s=screen();await s.newSheet();assert.equal(s.doc.items.length,0);assert.equal(s.message,'');
 s=screen();s.root.find('#dp-date').val('2026-11-17');s.doc.items[0].qty=0;assert.equal(await s.save(),false);assert.match(s.message,/greater than zero/);
 s=screen();s.item.get_value=()=> 'unadded';await s.review();assert.match(s.message,/still in the entry fields/);
 s=screen();s.root.find('#dp-date').val('2026-11-17');s.call=async()=>{throw Error('offline')};await s.save();assert.equal(s.doc.items[0].qty,1);assert.match(s.message,/Not saved/);assert.equal(s.busy,false);
 s=screen();s.call=async()=>{throw Error('disconnected')};s.refresh=async()=>{throw Error('offline')};await s.post();assert.match(s.message,/Connection lost/);assert.equal(s.busy,false);
 s=screen();s.doc.status='Failed';s.doc.items[0].error='<strong>Missing cost</strong><br>Fix valuation';s.renderRows();assert.match(s.root.find('.dp-rows').content,/dp-row-error/);assert(!s.root.find('.dp-rows').content.includes('<strong>Missing'));
 console.log('6 UI regressions passed: blank sheet, quantity validation, unfinished item, offline save, interrupted post, readable failure');
})().catch(e=>{console.error(e);process.exitCode=1});
