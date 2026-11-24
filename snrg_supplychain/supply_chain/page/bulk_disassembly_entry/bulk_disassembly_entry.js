frappe.pages['bulk-disassembly-entry'].on_page_load = function(wrapper) {
  wrapper.disassembly = new BulkDisassemblyScreen(wrapper);
};
frappe.pages['bulk-disassembly-entry'].on_page_show = function(wrapper) {
  wrapper.disassembly.activate();
  if (!wrapper.disassembly.loading && (frappe.route_options?.new_sheet || new URLSearchParams(window.location.search).get('new_sheet'))) {
    frappe.route_options = null; wrapper.disassembly.newSheet(); return;
  }
  const name = frappe.route_options?.disassembly_sheet || new URLSearchParams(window.location.search).get('sheet');
  if (name && !wrapper.disassembly.loading && wrapper.disassembly.doc?.name !== name) { frappe.route_options = null; wrapper.disassembly.open(name).catch(()=>wrapper.disassembly.feedback(__('Could not open this sheet. Check your connection and permissions.'),true)); }
  else if(wrapper.disassembly.doc?.status==='Queued') wrapper.disassembly.refresh();
};

class BulkDisassemblyScreen {
  constructor(wrapper) {
    this.page = frappe.ui.make_app_page({parent: wrapper, title: __('Bulk Disassembly'), single_column: true});
    this.api = 'snrg_supplychain.supply_chain.bulk_disassembly.';
    this.doc = null;
    this.busy = false;
    this.loading = true;
    this.dirty = false;
    this.poll = null;
    this.root = $('<div class="bulk-disassembly"></div>').appendTo(this.page.main);
    this.renderShell();this.activate();
    if(window.ResizeObserver){this.footerObserver=new ResizeObserver(()=>this.alignFooter());this.footerObserver.observe(this.root[0]);}
    window.addEventListener('resize',()=>this.alignFooter());
    this.page.add_menu_item(__('New sheet'), () => this.startNew());
    this.page.add_menu_item(__('Paste from Excel'), () => this.paste());
    this.page.add_menu_item(__('Sheet details'), () => {if(this.doc?.name)frappe.set_route('Form','Bulk Disassembly',this.doc.name);else frappe.msgprint(__('Save this sheet to view its details.'));});
    this.page.add_menu_item(__('Disassembly history'), () => frappe.set_route('List', 'Bulk Disassembly'));
    this.page.add_menu_item(__('Stations'), () => frappe.set_route('List', 'Production Station'));
    $(wrapper).on('hide', () => {clearTimeout(this.poll);document.body.classList.remove('bd-entry-active');});
    window.addEventListener('beforeunload',event=>{if(this.dirty){event.preventDefault();event.returnValue='';}});
    this.root.find('input,button').prop('disabled',true);
    this.feedback(__('Loading your saved draft…'));
    window.addEventListener('online',()=>{if(this.doc?.name&&!this.dirty)this.refresh().catch(()=>this.feedback(__('Connection unavailable. Your saved sheet can be reopened.'),true));});
    this.loadDraft().finally(()=>{
      this.loading=false;
      this.root.find('input,button').prop('disabled',false);
      if(this.doc)this.renderRows();
    });
  }
  esc(value) { return frappe.utils.escape_html(String(value ?? '')); }
  errorMessage(error){
    const message=String(error).replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();
    if(/allow zero valuation|allow_zero_valuation|valuation rate for|valuation rate missing/i.test(message))return __('Material valuation is missing. Ask the inventory or accounts team to record the correct incoming material cost, then review disassembly again. Posting remains blocked until a valid cost is available.');
    return message;
  }
  async call(method, args) { return (await frappe.call({method, args})).message; }
  renderShell() {
    this.root.html(`<style>
      [data-theme="dark"] .bulk-disassembly,[data-theme="dark"] .bd-review-dialog{--bd-danger-color:var(--red-300,#eb4c4c)}
      html:has(body.bd-entry-active){overflow:clip}body.bd-entry-active{overflow:clip}
      .bulk-disassembly {max-width:1050px;margin:auto;padding:16px 8px 110px;color:var(--text-color)}
      .bd-context,.bd-add,.bd-row,.bd-empty {background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;padding:16px;margin-bottom:12px}
      .bd-context,.bd-add {display:grid;grid-template-columns:2fr 1fr 1fr;gap:16px}
      .bd-warehouses {display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}.bd-warehouses .form-control{min-width:0}
      .bd-row-error{grid-column:1/-1;overflow-wrap:anywhere;line-height:1.5}.bd-review-dialog .modal-footer button{min-height:48px;font-size:16px}.bd-review-dialog summary{min-height:44px;padding:10px 0}.bd-review-dialog .modal-body{overflow-wrap:anywhere}.bd-missing-warehouse{font-size:13px;color:var(--text-muted);margin-bottom:6px}.bd-missing-items{padding-left:18px;margin:0 0 14px;color:var(--bd-danger-color,var(--red-600,#b42318))}.bd-missing-items li{margin-bottom:5px;line-height:1.4}
      .bd-context>div,.bd-warehouses>div,.bd-add>div{min-width:0}.bd-review-dialog .modal-header .btn-modal-close{min-width:44px;min-height:44px;display:flex;align-items:center;justify-content:center}.bd-missing-group{border-left:3px solid var(--bd-danger-color,var(--red-600,#b42318));padding-left:12px;margin:12px 0 16px}.bd-shortage-list p{margin-bottom:8px}.bd-review-dialog summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
      .bd-warning{color:var(--orange-700,#9a4d00)}
      .bd-add {grid-template-columns:3fr 1fr auto;align-items:end}
      .bulk-disassembly label {display:block;font-size:14px;font-weight:600;margin-bottom:6px}
      .bulk-disassembly input,.bulk-disassembly select,.bulk-disassembly button {min-height:48px;font-size:16px}
      .bulk-disassembly .frappe-control {margin-bottom:0}
      .bd-row {display:grid;grid-template-columns:minmax(0,1fr) 150px minmax(110px,280px) 48px;align-items:center;gap:16px}
      .bd-row-name {font-weight:600;overflow-wrap:anywhere}.bd-meta {font-size:13px;color:var(--text-muted);margin-top:4px;overflow-wrap:anywhere}
      .bd-top-status{display:flex;justify-content:flex-end;margin-bottom:12px}.bd-status-pill{font-size:13px;padding:6px 12px;white-space:nowrap}
      .bd-feedback {margin:8px 0;overflow-wrap:anywhere}.bd-feedback:empty{display:none}.bd-save-status{font-size:13px;color:var(--text-muted);margin-left:10px}.bd-save-status:empty{display:none}.bd-summary-line{display:flex;align-items:center;flex-wrap:wrap;gap:4px}.bd-error {color:var(--bd-danger-color,var(--red-600,#b42318))}
      .bd-bottom {position:fixed;bottom:0;left:var(--bd-footer-left,0px);right:var(--bd-footer-right,0px);background:var(--card-bg);border-top:1px solid var(--border-color);padding:12px max(16px,env(safe-area-inset-right)) calc(12px + env(safe-area-inset-bottom));z-index:100}
      .bd-bottom-inner {max-width:1030px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:12px}
      .bd-actions {display:flex;gap:8px}.bd-empty {text-align:center;padding:40px 20px}
      .bd-history {margin:12px 0}.bd-row input {width:100%}.bd-state {overflow-wrap:anywhere}.bd-state a {display:block;min-height:44px;padding-top:8px;text-decoration:underline}
      .bulk-disassembly button:focus-visible,.bulk-disassembly input:focus-visible {outline:2px solid var(--primary);outline-offset:2px}
      @media(max-width:640px){.bd-bottom{left:0;right:0}.bd-warehouses{grid-template-columns:1fr;gap:12px}.bd-context{grid-template-columns:1fr 1fr}.bd-station{grid-column:1/-1}.bd-add{grid-template-columns:1fr 100px}.bd-item-picker{grid-column:1/-1}.bd-row{grid-template-columns:1fr 110px;gap:12px}.bd-row .bd-state{grid-column:1}.bd-remove{grid-column:2;justify-self:end}.bd-actions{flex-wrap:wrap}.bd-bottom-inner{align-items:center}.bd-empty{padding:24px 12px}.bd-bottom-inner{display:grid;grid-template-columns:1fr;gap:8px}.bd-actions{display:grid;grid-template-columns:1fr 1.4fr}.bd-summary{font-size:14px}.bulk-disassembly{padding-bottom:160px}}
      .bd-settings-bar{display:none}.bd-field-error:empty{display:none}.bd-field-error{color:var(--bd-danger-color,var(--red-600,#b42318));font-size:13px;line-height:1.4;margin-top:6px;overflow-wrap:anywhere}.bulk-disassembly [aria-invalid="true"]{border:1px solid var(--bd-danger-color,var(--red-600,#b42318))}
      .bd-table-wrap{border:1px solid var(--border-color);border-radius:12px;overflow:clip;background:var(--card-bg);margin-bottom:12px}.bd-table{width:100%;table-layout:fixed;border-collapse:collapse}.bd-table th{position:sticky;top:48px;z-index:2;font-size:13px;color:var(--text-muted);font-weight:600;text-align:left;padding:10px 12px;background:var(--subtle-fg,var(--card-bg));border-bottom:1px solid var(--border-color)}.bd-table .bd-row{display:table-row;border:0;border-radius:0;margin:0;padding:0}.bd-table td{padding:8px 12px;vertical-align:middle;border-bottom:1px solid var(--border-color)}.bd-table tbody tr:last-child td{border-bottom:0}.bd-table .bd-quantity-col{width:150px}.bd-table .bd-state-col{width:200px}.bd-table .bd-action-col{width:72px}.bd-table .bd-qty-label{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.bd-table .bd-row-error td{padding-top:0}.bd-table .bd-state a{min-height:44px}.bd-table .bd-remove{width:48px}.bd-table .bd-meta{margin-top:2px}.bd-table .bd-row-name{line-height:1.35}
      .bd-review-dialog .modal-body{overscroll-behavior:contain}.bd-review-dialog .modal-dialog{margin:16px auto}.bd-review-dialog .modal-content{overflow:hidden;display:flex;flex-direction:column;max-height:calc(100dvh - 32px)}.bd-review-dialog .modal-header,.bd-review-dialog .modal-footer{flex-shrink:0}.bd-review-dialog .modal-body{min-height:0;overflow-y:auto;max-height:none}.bd-review-dialog .bd-blockers{border-left:3px solid var(--bd-danger-color,var(--red-600,#b42318));padding-left:12px;margin-bottom:20px}.bd-blockers h4{margin-top:0}.bd-blocker-group{margin-top:12px}.bd-blocker-list{padding-left:18px;margin:6px 0 0}.bd-blocker-list li{margin-bottom:10px;line-height:1.4}.bd-blocker-reasons{font-size:13px;color:var(--bd-danger-color,var(--red-600,#b42318));margin-top:3px}.bd-blocker-numbers{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--text-color);margin-top:4px}.bd-review-context{font-size:13px;color:var(--text-muted);line-height:1.6;margin-bottom:16px}
      @media(max-width:640px){.bd-settings{border:1px solid var(--border-color);border-radius:12px;padding:12px;margin-bottom:16px;background:var(--card-bg)}.bd-settings-bar{display:flex;align-items:center;gap:12px;justify-content:space-between}.bd-settings-summary{min-width:0;font-size:14px;overflow-wrap:anywhere}.bd-settings-summary small{display:block;color:var(--text-muted);margin-top:4px;font-size:12px}.bd-settings-toggle{flex-shrink:0}.bd-settings.is-collapsed .bd-settings-fields{display:none}.bd-settings:not(.is-collapsed) .bd-settings-fields{padding-top:12px}.bd-settings .bd-context{padding:0;border:0;border-radius:0}.bd-settings .bd-warehouses{margin-bottom:0}.bd-table-wrap{border:0;background:transparent;overflow:visible}.bd-table,.bd-table tbody{display:block;width:100%}.bd-table thead,.bd-table colgroup{display:none}.bd-table .bd-row{display:grid;grid-template-columns:minmax(0,1fr) 110px;gap:12px;border:1px solid var(--border-color);border-radius:12px;margin-bottom:12px;padding:16px;background:var(--card-bg)}.bd-table td{display:block;border:0;padding:0;min-width:0}.bd-table .bd-qty-label{position:static;width:auto;height:auto;clip:auto;white-space:normal;margin-bottom:6px}.bd-table .bd-state{grid-column:1}.bd-table .bd-action-cell{grid-column:2;justify-self:end}.bd-table .bd-row-error{display:block;margin:-4px 0 12px;padding:12px 16px;border:1px solid var(--border-color);border-radius:12px;background:var(--card-bg)}.bd-table .bd-row-error td{padding:0}.bd-blocker-numbers{gap:8px}}
    </style>
    <div class="bd-top-status"><span class="indicator-pill gray bd-status-pill" role="status" aria-live="polite">${__('Loading')}</span></div>
    <p>${__('Disassemble finished goods and recover components using the approved BOM.')}</p>
    <section class="bd-settings"><div class="bd-settings-bar"><div class="bd-settings-summary"></div><button class="btn btn-default bd-settings-toggle" type="button" aria-expanded="true" aria-controls="bd-settings-fields">${__('Change')}</button></div><div class="bd-settings-fields" id="bd-settings-fields">
    <div class="bd-context">
      <div class="bd-station"></div>
      <div><label for="bd-date">${__('Disassembly date')}</label><input id="bd-date" class="form-control" type="date"><div class="bd-field-error bd-date-error" id="bd-date-error"></div></div>
      <div><label for="bd-shift">${__('Shift / run (optional)')}</label><input id="bd-shift" class="form-control" maxlength="140"></div>
    </div>
    <div class="bd-warehouses"><div class="bd-source"></div><div class="bd-target"></div></div>
    </div></section>
    <div class="bd-feedback" role="status" aria-live="polite"></div>
    <div class="bd-add">
      <div class="bd-item-picker"></div>
      <div><label for="bd-add-qty">${__('Quantity to disassemble')}</label><input id="bd-add-qty" class="form-control" type="number" inputmode="decimal" min="0" step="any"><div class="bd-field-error bd-add-qty-error" id="bd-add-qty-error"></div></div>
      <button class="btn btn-primary bd-add-button">${__('Add & next')}</button>
    </div>
    <div class="bd-rows"></div>
    <div class="bd-history"><button class="btn btn-default bd-history-button">${__('Today’s entries')}</button></div>
    <div class="bd-bottom"><div class="bd-bottom-inner"><div class="bd-summary-line"><span class="bd-summary"></span><span class="bd-save-status" role="status" aria-live="polite"></span></div><div class="bd-actions"><button class="btn btn-default bd-save">${__('Save draft')}</button><button class="btn btn-primary bd-review">${__('Review disassembly')}</button></div></div></div>`);
    this.station = frappe.ui.form.make_control({parent:this.root.find('.bd-station'),df:{fieldname:'station',fieldtype:'Link',options:'Production Station',label:__('Station'),reqd:1,get_query:()=>({filters:{enabled:1,consumption_method:'Stocked components'}}),change:()=>this.stationChanged()},render_input:true});
    const warehouseControl=(selector,fieldname,label)=>frappe.ui.form.make_control({parent:this.root.find(selector),df:{fieldname,fieldtype:'Link',options:'Warehouse',label:__(label),reqd:1,get_query:()=>({filters:{company:this.stationConfig?.company||this.doc?.company||'__select_station__',is_group:0,disabled:0}}),change:()=>this.warehouseChanged()},render_input:true});
    this.sourceWarehouse=warehouseControl('.bd-source','source_warehouse','Source warehouse');
    this.targetWarehouse=warehouseControl('.bd-target','target_warehouse','Target warehouse');
    this.item = frappe.ui.form.make_control({parent:this.root.find('.bd-item-picker'),df:{fieldname:'item',fieldtype:'Link',options:'Item',label:__('Item name or code'),get_query:()=>({filters:{disabled:0,is_stock_item:1,has_variants:0}})},render_input:true});
    for(const name of ['station','source','target','item-picker'])this.root.find('.bd-'+name).append(`<div class="bd-field-error bd-${name}-error" id="bd-${name}-error"></div>`);
    this.root.find('#bd-date').val(frappe.datetime.get_today());
    this.root.on('click','.bd-settings-toggle',()=>{this.settingsCollapsed=!this.settingsCollapsed;this.renderSettings();});
    this.root.on('click','.bd-add-button',()=>this.add());
    this.root.on('keydown','#bd-add-qty',e=>{if(e.key==='Enter')this.add();});
    this.root.on('input','.bd-item-picker input,#bd-add-qty',()=>this.clearFieldErrors());
    this.root.on('input','#bd-date,#bd-shift',()=>{this.clearFieldErrors();this.changed();this.renderSettings();});
    this.root.on('input','.bd-qty',e=>{this.doc.items[Number(e.target.dataset.index)].qty=Number(e.target.value);this.clearFieldErrors();this.changed();});
    this.root.on('click','.bd-remove',e=>{this.doc.items.splice(Number(e.currentTarget.dataset.index),1);this.changed();this.renderRows();});
    this.root.on('click','.bd-paste',()=>this.paste());
    this.root.on('click','.bd-save',()=>this.save());
    this.root.on('click','.bd-review',()=>this.review());
    this.root.on('click','.bd-new',()=>this.startNew());
    this.root.on('click','.bd-history-button',()=>{frappe.route_options={posting_date:frappe.datetime.get_today()};frappe.set_route('List','Bulk Disassembly');});
  }
  feedback(text,error=false){
    this.root.find('.bd-feedback').attr('role',error?'alert':'status').attr('aria-live',error?'assertive':'polite').text(error?text:'').toggleClass('bd-error',error);
    this.root.find('.bd-save-status').text(error?__('Needs attention'):text);
  }
  activate(){
    document.body.classList.add('bd-entry-active');
    document.scrollingElement.scrollTop=0;
    this.alignFooter();
  }
  alignFooter(){
    if(!this.root[0]?.getClientRects().length)return;
    const rect=this.root[0].getBoundingClientRect();
    this.root[0].style.setProperty('--bd-footer-left',`${Math.max(0,rect.left)}px`);
    this.root[0].style.setProperty('--bd-footer-right',`${Math.max(0,window.innerWidth-rect.right)}px`);
  }
  renderSettings(){
    const ready=Boolean(this.station?.get_value()&&this.sourceWarehouse?.get_value()&&this.targetWarehouse?.get_value());
    this.root.find('.bd-settings').toggleClass('is-collapsed',ready&&Boolean(this.settingsCollapsed));
    this.root.find('.bd-settings-toggle').attr('aria-expanded',String(!ready||!this.settingsCollapsed)).text(ready&&this.settingsCollapsed?__('Change'):__('Done'));
    const station=this.station?.get_value()||__('Disassembly settings');
    const warehouses=ready?`${this.sourceWarehouse.get_value()} → ${this.targetWarehouse.get_value()}`:__('Choose a station and warehouses');
    this.root.find('.bd-settings-summary').html(`<strong>${this.esc(station)}</strong> · ${this.esc(this.root.find('#bd-date').val()||'')}<small>${this.esc(warehouses)}</small>`);
  }
  clearFieldErrors(){
    this.root.find('.bd-field-error').text('');
    this.root.find('[aria-invalid="true"]').removeAttr('aria-invalid aria-describedby');
  }
  fieldError(selector,message){
    const field=this.root.find(selector);field.attr('aria-invalid','true');
    const error=field.closest('.frappe-control').length?field.closest('.frappe-control').parent().find('.bd-field-error'):field.parent().find('.bd-field-error');
    if(error.length){error.attr('role','alert').text(message);if(error.attr('id'))field.attr('aria-describedby',error.attr('id'));}
    else this.feedback(message,true);
  }
  validateQuantities(){
    let valid=true;
    this.doc.items.forEach((row,index)=>{if(!Number.isFinite(Number(row.qty))||Number(row.qty)<=0){valid=false;this.fieldError(`#bd-qty-${index}`,__('Enter a quantity greater than zero.'));}});
    return valid;
  }
  startNew(){
    if(this.busy||this.loading)return;
    if(this.dirty||this.item.get_value()||this.root.find('#bd-add-qty').val())frappe.confirm(__('Discard unsaved changes?'),()=>this.newSheet());
    else this.newSheet();
  }
  rememberSheet(name){
    if(!window.location.protocol.startsWith('http')||!window.location.pathname.endsWith('/bulk-disassembly-entry'))return;
    const url=new URL(window.location.href);
    url.searchParams.delete('new_sheet');url.searchParams.delete('disassembly_sheet');
    if(name)url.searchParams.set('sheet',name);else {url.searchParams.delete('sheet');url.searchParams.set('new_sheet','1');}
    window.history.replaceState(window.history.state,'',url);
  }
  async newSheet(){
    if(this.busy)return;
    const wasLoading=this.loading;this.loading=true;
    clearTimeout(this.poll);clearTimeout(this.saveTimer);
    this.rememberSheet(null);
    this.root.find('#bd-date').val(frappe.datetime.get_today());
    this.root.find('#bd-shift,#bd-add-qty').val('');
    this.applyingWarehouses=true;
    try {
      await this.item.set_value('');
      await this.sourceWarehouse.set_value(this.stationConfig?.target_warehouse||'');
      await this.targetWarehouse.set_value(this.stationConfig?.source_warehouse||'');
      this.doc={doctype:'Bulk Disassembly',items:[],status:'Draft',station:this.station.get_value(),company:this.stationConfig?.company,source_warehouse:this.sourceWarehouse.get_value(),target_warehouse:this.targetWarehouse.get_value()};
      this.settingsCollapsed=false;this.dirty=false;this.clearFieldErrors();this.feedback('');
    }finally{this.applyingWarehouses=false;this.loading=wasLoading;this.renderRows();}
  }
  async open(name){
    if(this.busy)return;
    clearTimeout(this.poll);clearTimeout(this.saveTimer);
    this.loading=true;this.root.find('input,button').prop('disabled',true);
    try {
    this.doc=await frappe.db.get_doc('Bulk Disassembly',name);
    await this.station.set_value(this.doc.station);await this.stationChanged();
    this.root.find('#bd-date').val(this.doc.posting_date);
    this.root.find('#bd-shift').val(this.doc.shift||'');
    this.settingsCollapsed=true;this.dirty=false;this.rememberSheet(this.doc.name);this.renderRows();this.feedback(__('Saved'));
    if(this.doc.status==='Queued')await this.refresh();
    } finally {this.loading=false;this.root.find('input,button').prop('disabled',false);if(this.doc)this.renderRows();}
  }
  async loadDraft(){
    try {
      if(frappe.route_options?.new_sheet || new URLSearchParams(window.location.search).get('new_sheet')){frappe.route_options=null;await this.newSheet();return;}
      const requested=frappe.route_options?.disassembly_sheet||new URLSearchParams(window.location.search).get('sheet');
      if(requested){frappe.route_options=null;await this.open(requested);return;}
      await this.newSheet();
    }catch(e){await this.newSheet();this.feedback(__('Could not load drafts. Check your connection and permissions.'),true);}
  }
  async stationChanged(){
    const name=this.station.get_value();
    const markDirty=!this.loading;
    if(!name){this.stationConfig=null;if(this.doc&&!this.loading){this.applyingWarehouses=true;this.sourceWarehouse.set_value('');this.targetWarehouse.set_value('');this.applyingWarehouses=false;this.doc.station='';this.doc.source_warehouse='';this.doc.target_warehouse='';this.changed();}return;}
    try {
      const station=await frappe.db.get_doc('Production Station',name);
      if(name!==this.station.get_value())return;
      this.stationConfig=station;
      const restore=!markDirty&&this.doc?.station===name;
      this.applyingWarehouses=true;
      try {
        await this.sourceWarehouse.set_value(restore&&this.doc.source_warehouse?this.doc.source_warehouse:station.target_warehouse);
        await this.targetWarehouse.set_value(restore&&this.doc.target_warehouse?this.doc.target_warehouse:station.source_warehouse);
      } finally {this.applyingWarehouses=false;}
      if(this.doc){this.doc.company=station.company;this.doc.station=name;this.doc.source_warehouse=this.sourceWarehouse.get_value();this.doc.target_warehouse=this.targetWarehouse.get_value();}
      if(this.doc&&markDirty){this.settingsCollapsed=true;this.clearFieldErrors();this.changed();}this.renderSettings();
    }catch(e){this.feedback(__('Could not load station settings.'),true);}
  }
  warehouseChanged(){
    if(this.loading||this.applyingWarehouses||!this.doc||this.doc.status!=='Draft')return;
    const source=this.sourceWarehouse.get_value(),target=this.targetWarehouse.get_value();
    if(this.doc.source_warehouse===source&&this.doc.target_warehouse===target)return;
    this.doc.source_warehouse=source;this.doc.target_warehouse=target;this.clearFieldErrors();this.changed();this.renderSettings();
  }
  changed(){
    if(this.loading)return;
    this.dirty=true;this.feedback(__('Unsaved'));
    clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>{if(this.doc?.items.length&&!this.busy&&this.doc.status==='Draft')this.save();},1500);
  }
  paste(){
    if(this.busy||this.doc?.status!=='Draft')return;
    const dialog=new frappe.ui.Dialog({title:__('Paste item codes and quantities'),fields:[{fieldname:'lines',fieldtype:'Small Text',label:__('Two columns: item code, quantity'),description:__('Copy two columns from Excel. Each item must appear once.'),reqd:1}],primary_action_label:__('Add items'),primary_action:async values=>{
      if(this.busy)return;this.busy=true;
      try {
        const rows=values.lines.trim().split(/\r?\n/).map(line=>line.trim().split(/\t|,/));
        const codes=new Set(this.doc.items.map(r=>r.item_code));
        if(rows.length+this.doc.items.length>100)throw new Error(__('Maximum 100 rows per sheet.'));
        for(const [code,quantity,...extra] of rows){if(!code||!quantity||extra.length||!Number.isFinite(Number(quantity))||Number(quantity)<=0||codes.has(code))throw new Error(__('Use unique item codes with positive quantities, in two columns.'));codes.add(code);}
        const additions=[];
        for(const [code,quantity] of rows){const item=await frappe.db.get_doc('Item',code);additions.push({doctype:'Bulk Disassembly Item',item_code:code,item_name:item.item_name,uom:item.stock_uom,qty:Number(quantity),status:'Pending'});}
        this.doc.items.push(...additions);dialog.hide();this.changed();this.renderRows();
      }catch(e){frappe.msgprint(this.esc(e.message||__('Could not load items. Check the pasted codes.')));}
      finally{this.busy=false;this.renderRows();}
    }});dialog.show();
  }
  async add(){
    if(this.busy||this.doc?.status!=='Draft')return;
    const code=this.item.get_value(),qty=Number(this.root.find('#bd-add-qty').val());
    this.clearFieldErrors();
    if(!code)this.fieldError('.bd-item-picker input',__('Select an item.'));
    if(!Number.isFinite(qty)||qty<=0)this.fieldError('#bd-add-qty',__('Enter a quantity greater than zero.'));
    if(!code||!Number.isFinite(qty)||qty<=0){this.feedback(__('Check the highlighted entry fields.'),true);return;}
    if(this.doc.items.some(r=>r.item_code===code)){this.fieldError('.bd-item-picker input',__('Already on this sheet. Edit its quantity below.'));return;}
    if(this.doc.items.length>=100){this.feedback(__('Maximum 100 rows per sheet.'),true);return;}
    this.busy=true;
    try {const item=await frappe.db.get_doc('Item',code);this.doc.items.push({doctype:'Bulk Disassembly Item',item_code:code,item_name:item.item_name,uom:item.stock_uom,qty,status:'Pending'});await this.item.set_value('');this.root.find('#bd-add-qty').val('');this.changed();this.renderRows();this.item.$input.focus();}
    catch(e){this.feedback(__('Could not add the item. Check the item code and connection, then retry.'),true);}
    finally{this.busy=false;this.renderRows();}
  }
  renderRows(){
    const editable=this.doc.status==='Draft';
    const statusColor={'Draft':'gray','Queued':'blue','Posted':'green','Partially Posted':'orange','Failed':'red'}[this.doc.status]||'gray';
    this.root.find('.bd-status-pill').attr('class',`indicator-pill ${statusColor} bd-status-pill`).text(__(this.doc.status));
    this.renderSettings();this.alignFooter();
    const rows=this.doc.items.map((r,i)=>`<tr class="bd-row"><td><div class="bd-row-name">${this.esc(r.item_name||r.item_code)}</div><div class="bd-meta">${this.esc(r.item_code)} · ${this.esc(r.uom||'')}</div></td><td><label class="bd-qty-label" for="bd-qty-${i}">${__('Quantity')}<span class="sr-only"> — ${this.esc(r.item_code)}</span></label><input id="bd-qty-${i}" class="form-control bd-qty" data-index="${i}" type="number" inputmode="decimal" step="any" min="0" value="${this.esc(r.qty)}" ${editable?'':'disabled'}><div class="bd-field-error" id="bd-qty-error-${i}"></div></td><td class="bd-state">${this.esc(r.status||'Pending')}${r.stock_entry?`<a href="${this.esc(frappe.utils.get_form_link('Stock Entry',r.stock_entry))}">${this.esc(r.stock_entry)}</a>`:''}</td><td class="bd-action-cell">${editable?`<button class="btn btn-default bd-remove" data-index="${i}" aria-label="${this.esc(__('Remove {0}',[r.item_code]))}">×</button>`:''}</td></tr>${r.error?`<tr class="bd-error bd-row-error"><td colspan="4">${this.esc(this.errorMessage(r.error))}</td></tr>`:''}`).join('');
    this.root.find('.bd-rows').html(this.doc.items.length?`<div class="bd-table-wrap"><table class="bd-table" aria-label="${__('Disassembly items')}"><colgroup><col><col class="bd-quantity-col"><col class="bd-state-col"><col class="bd-action-col"></colgroup><thead><tr><th scope="col">${__('Item')}</th><th scope="col">${__('Quantity to disassemble')}</th><th scope="col">${__('Status')}</th><th scope="col"><span class="sr-only">${__('Actions')}</span></th></tr></thead><tbody>${rows}</tbody></table></div>`:`<div class="bd-empty"><strong>${__('Start with an item and quantity')}</strong><p class="bd-meta">${__('Add each finished item to disassemble. You can post one item now or several together.')}</p></div>`);
    this.root.find('.bd-summary').text(`${this.doc.items.length} ${this.doc.items.length===1?__('item'):__('items')}`);
    this.root.find('.bd-add,.bd-paste').toggle(editable);
    this.root.find('.bd-save').toggle(editable);
    this.root.find('.bd-review').prop('disabled',this.loading||this.busy||this.doc.status==='Posted'||!this.doc.items.length);
    this.root.find('#bd-date,#bd-shift').prop('disabled',!editable);
    this.station.$input.prop('disabled',!editable);
    this.sourceWarehouse.$input.prop('disabled',!editable);this.targetWarehouse.$input.prop('disabled',!editable);
    this.root.find('.bd-review').text(this.doc.status==='Posted'?__('Disassembly posted'):this.doc.status==='Queued'?__('Check / resume posting'):this.doc.status==='Draft'?__('Review disassembly'):__('Review failed rows'));
  }
  async save(){
    clearTimeout(this.saveTimer);
    if(this.busy||!this.doc||this.doc.status!=='Draft')return false;
    this.clearFieldErrors();
    const required=[['.bd-station input',this.station.get_value(),__('Choose a disassembly station.')],['.bd-source input',this.sourceWarehouse.get_value(),__('Choose a source warehouse.')],['.bd-target input',this.targetWarehouse.get_value(),__('Choose a target warehouse.')]];
    if(required.some(([,value])=>!value)){this.settingsCollapsed=false;this.renderSettings();required.forEach(([selector,value,message])=>{if(!value)this.fieldError(selector,message);});this.feedback(__('Complete the highlighted disassembly settings.'),true);return false;}
    if(!this.doc.items.length){this.fieldError('.bd-item-picker input',__('Add at least one item to this sheet.'));return false;}
    if(!this.root.find('#bd-date').val()){this.settingsCollapsed=false;this.renderSettings();this.fieldError('#bd-date',__('Choose a disassembly date.'));return false;}
    if(!this.validateQuantities()){this.feedback(__('Check the highlighted quantities.'),true);return false;}
    const active=typeof document!=='undefined'?document.activeElement:null;
    const restoreId=active?.id&&this.root[0]?.contains(active)?active.id:null;
    this.busy=true;this.root.find('input,button').prop('disabled',true);this.feedback(__('Saving…'));
    try {
      this.doc.source_warehouse=this.sourceWarehouse.get_value();this.doc.target_warehouse=this.targetWarehouse.get_value();
      this.doc.station=this.station.get_value();this.doc.posting_date=this.root.find('#bd-date').val();this.doc.shift=this.root.find('#bd-shift').val();this.doc.posting_time=this.doc.posting_time||frappe.datetime.now_time();
      const saved=await this.call('frappe.client.save',{doc:this.doc});
      this.doc=saved;this.dirty=false;this.rememberSheet(saved.name);this.feedback(__('Saved'));this.renderRows();return true;
    }catch(e){this.feedback(__('Not saved. Your changes remain on this screen. Check the connection and retry.'),true);return false;}
    finally{this.busy=false;this.root.find('input,button').prop('disabled',false);this.renderRows();if(restoreId&&this.root[0]?.getClientRects().length)document.getElementById(restoreId)?.focus({preventScroll:true});}
  }
  async review(){
    if(this.busy)return;
    if(this.doc.status==='Draft'&&(this.item.get_value()||this.root.find('#bd-add-qty').val())){this.feedback(__('An item is still in the entry fields. Add it to the sheet or clear those fields before reviewing.'),true);return;}
    if(this.doc.status==='Draft'&&(!this.doc.name||this.dirty)&&!await this.save())return;
    if(!this.doc.name)return;
    this.busy=true;
    try {
      const result=await this.call(this.api+'review',{name:this.doc.name});
      this.reviewToken=result.review_token;
      const shortage=result.shortages.length>0;
      const missing=result.valuation_issues||[];
      const materialNames=new Map(result.rows.flatMap(row=>[...(row.consumed||[]),...row.materials].map(m=>[m.item_code,m.item_name])));
      const groups=new Map();
      const getIssue=(m)=>{if(!groups.has(m.warehouse))groups.set(m.warehouse,new Map());const items=groups.get(m.warehouse);if(!items.has(m.item_code))items.set(m.item_code,{...m,item_name:m.item_name||materialNames.get(m.item_code)});return items.get(m.item_code);};
      missing.forEach(m=>{getIssue(m).missingCost=true;});
      result.shortages.forEach(m=>{Object.assign(getIssue(m),m,{shortage:true});});
      const blocked=groups.size>0;
      const issues=Array.from(groups.values()).reduce((sum,items)=>sum+items.size,0);
      const blockers=blocked?`<section class="bd-blockers" role="region" aria-label="${__('Posting blocked')}"><h4>${__('Posting blocked')} · ${issues} ${issues===1?__('material'):__('materials')}</h4><p>${__('Resolve the material issues below, then review again.')}</p>${Array.from(groups,([warehouse,items])=>`<div class="bd-blocker-group"><div class="bd-missing-warehouse">${__('Source warehouse')}: <strong>${this.esc(warehouse)}</strong></div><ul class="bd-blocker-list">${Array.from(items.values(),m=>`<li><strong>${this.esc(m.item_code)}</strong>${m.item_name?` — ${this.esc(m.item_name)}`:''}<div class="bd-blocker-reasons">${[m.missingCost?__('Missing valuation'):null,m.shortage?__('Insufficient stock'):null].filter(Boolean).join(' · ')}</div>${m.shortage?`<div class="bd-blocker-numbers"><span>${__('Required')}: <strong>${this.esc(m.required)}</strong></span><span>${__('Available')}: <strong>${this.esc(m.available)}</strong></span><span>${__('Shortage')}: <strong>${this.esc(Number(Math.max(0,m.required-m.available).toFixed(6)))}</strong></span></div>`:''}</li>`).join('')}</ul></div>`).join('')}<small>${__('Add valid material costs, replenish the source warehouse, or reduce quantities as applicable.')}</small></section>`:'';
      const dialog=new frappe.ui.Dialog({title:__('Review disassembly'),fields:[{fieldname:'summary',fieldtype:'HTML'}],primary_action_label:blocked?__('Back to sheet'):__('Post disassembly'),primary_action:async()=>{dialog.hide();if(!blocked)await this.post();}});
      dialog.fields_dict.summary.$wrapper.html(`${blockers}<div class="bd-review-context">${this.esc(this.doc.station)} · ${this.esc(this.doc.posting_date)}<br>${__('Source')}: ${this.esc(this.doc.source_warehouse)}<br>${__('Target')}: ${this.esc(this.doc.target_warehouse)}</div>${result.rows.map(r=>`<p><strong>${this.esc(r.item_code)} — ${this.esc(r.qty)} ${this.esc(r.uom||'')}</strong><br><small>${this.esc(r.bom_no)}</small></p><details><summary>${__('Components to recover')}</summary>${r.materials.map(m=>`<p>${this.esc(m.item_name||m.item_code)}: ${this.esc(m.qty)} ${this.esc(m.uom)}</p>`).join('')}</details>`).join('')}`);
      dialog.$wrapper.addClass('bd-review-dialog');
      dialog.show();
    }catch(e){this.feedback(__('Could not review disassembly. Check the message above and retry.'),true);}
    finally{this.busy=false;this.renderRows();}
  }
  async post(){
    if(this.busy)return;this.busy=true;
    try {await this.call(this.api+'post',{name:this.doc.name,token:this.reviewToken});this.feedback(__('Posting started. You can safely return to this sheet.'));await this.refresh();}
    catch(e){this.feedback(__('Posting could not be confirmed. Check the sheet status before retrying.'),true);try{await this.refresh();}catch(connectionError){this.feedback(__('Connection lost. Reconnect or reload to recover this saved sheet before retrying.'),true);}}
    finally{this.busy=false;this.renderRows();}
  }
  async refresh(){
    clearTimeout(this.poll);
    this.doc=await frappe.db.get_doc('Bulk Disassembly',this.doc.name);this.renderRows();
    if(this.doc.status==='Queued')this.poll=setTimeout(()=>this.refresh().catch(()=>this.feedback(__('Connection lost. Reopen the saved sheet to check posting status.'),true)),2500);
    else if(this.doc.status==='Draft')this.feedback(__('Saved'));
    else this.feedback(`${this.doc.status} · ${this.doc.items.filter(r=>r.status==='Posted').length}/${this.doc.items.length} ${__('entries posted')}`);
  }
}
