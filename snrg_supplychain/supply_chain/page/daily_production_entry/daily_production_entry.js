frappe.pages['daily-production-entry'].on_page_load = function(wrapper) {
  wrapper.production = new DailyProductionScreen(wrapper);
};
frappe.pages['daily-production-entry'].on_page_show = function(wrapper) {
  wrapper.production.activate();
  if (!wrapper.production.loading && (frappe.route_options?.new_sheet || new URLSearchParams(window.location.search).get('new_sheet'))) {
    frappe.route_options = null; wrapper.production.newSheet(); return;
  }
  const name = frappe.route_options?.production_sheet || new URLSearchParams(window.location.search).get('sheet');
  if (name && !wrapper.production.loading && wrapper.production.doc?.name !== name) { frappe.route_options = null; wrapper.production.open(name).catch(()=>wrapper.production.feedback(__('Could not open this sheet. Check your connection and permissions.'),true)); }
  else if(wrapper.production.doc?.status==='Queued') wrapper.production.refresh();
};

class DailyProductionScreen {
  constructor(wrapper) {
    this.page = frappe.ui.make_app_page({parent: wrapper, title: __('Bulk Production'), single_column: true});
    this.api = 'snrg_supplychain.supply_chain.daily_production.';
    this.doc = null;
    this.busy = false;
    this.loading = true;
    this.dirty = false;
    this.poll = null;
    this.root = $('<div class="daily-production"></div>').appendTo(this.page.main);
    this.renderShell();this.activate();
    if(window.ResizeObserver){this.footerObserver=new ResizeObserver(()=>this.alignFooter());this.footerObserver.observe(this.root[0]);}
    window.addEventListener('resize',()=>this.alignFooter());
    this.page.add_menu_item(__('New sheet'), () => this.startNew());
    this.deleteDraftMenu=this.page.add_menu_item(__('Delete draft'), () => this.deleteDraft());
    this.page.add_menu_item(__('Paste from Excel'), () => this.paste());
    this.page.add_menu_item(__('Sheet details'), () => {if(this.doc?.name)frappe.set_route('Form','Daily Production',this.doc.name);else frappe.msgprint(__('Save this sheet to view its details.'));});
    this.page.add_menu_item(__('Production history'), () => frappe.set_route('List', 'Daily Production'));
    this.page.add_menu_item(__('Production stations'), () => frappe.set_route('List', 'Production Station'));
    $(wrapper).on('hide', () => {clearTimeout(this.poll);document.body.classList.remove('dp-entry-active');});
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
    if(/allow zero valuation|allow_zero_valuation|valuation rate for|valuation rate missing/i.test(message))return __('Material valuation is missing. Ask the inventory or accounts team to record the correct incoming material cost, then review production again. Posting remains blocked until a valid cost is available.');
    return message;
  }
  async call(method, args) { return (await frappe.call({method, args})).message; }
  renderShell() {
    this.root.html(`<style>
      [data-theme="dark"] .daily-production,[data-theme="dark"] .dp-review-dialog{--dp-danger-color:var(--red-300,#eb4c4c)}
      html:has(body.dp-entry-active){overflow:clip}body.dp-entry-active{overflow:clip}
      .daily-production {max-width:1050px;margin:auto;padding:16px 8px 110px;color:var(--text-color)}
      .dp-context,.dp-add,.dp-row,.dp-empty {background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;padding:16px;margin-bottom:12px}
      .dp-context,.dp-add {display:grid;grid-template-columns:2fr 1fr 1fr;gap:16px}
      .dp-warehouses {display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}.dp-warehouses .form-control{min-width:0}
      .dp-row-error{grid-column:1/-1;overflow-wrap:anywhere;line-height:1.5}.dp-review-dialog .modal-footer button{min-height:48px;font-size:16px}.dp-review-dialog summary{min-height:44px;padding:10px 0}.dp-review-dialog .modal-body{overflow-wrap:anywhere}.dp-missing-warehouse{font-size:13px;color:var(--text-muted);margin-bottom:6px}.dp-missing-items{padding-left:18px;margin:0 0 14px;color:var(--dp-danger-color,var(--red-600,#b42318))}.dp-missing-items li{margin-bottom:5px;line-height:1.4}
      .dp-context>div,.dp-warehouses>div,.dp-add>div{min-width:0}.dp-review-dialog .modal-header .btn-modal-close{min-width:44px;min-height:44px;display:flex;align-items:center;justify-content:center}.dp-missing-group{border-left:3px solid var(--dp-danger-color,var(--red-600,#b42318));padding-left:12px;margin:12px 0 16px}.dp-shortage-list p{margin-bottom:8px}.dp-review-dialog summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
      .dp-warning{color:var(--orange-700,#9a4d00)}
      .dp-add {grid-template-columns:3fr 1fr auto;align-items:end}
      .daily-production label {display:block;font-size:14px;font-weight:600;margin-bottom:6px}
      .daily-production input,.daily-production select,.daily-production button {min-height:48px;font-size:16px}
      .daily-production .frappe-control {margin-bottom:0}
      .dp-row {display:grid;grid-template-columns:minmax(0,1fr) 150px minmax(110px,280px) 48px;align-items:center;gap:16px}
      .dp-row-name {font-weight:600;overflow-wrap:anywhere}.dp-meta {font-size:13px;color:var(--text-muted);margin-top:4px;overflow-wrap:anywhere}
      .dp-top-status{display:flex;justify-content:flex-end;margin-bottom:12px}.dp-status-pill{font-size:13px;padding:6px 12px;white-space:nowrap}
      .dp-feedback {margin:8px 0;overflow-wrap:anywhere}.dp-feedback:empty{display:none}.dp-save-status{font-size:13px;color:var(--text-muted);margin-left:10px}.dp-save-status:empty{display:none}.dp-summary-line{display:flex;align-items:center;flex-wrap:wrap;gap:4px}.dp-error {color:var(--dp-danger-color,var(--red-600,#b42318))}
      .dp-bottom {position:fixed;bottom:0;left:var(--dp-footer-left,0px);right:var(--dp-footer-right,0px);background:var(--card-bg);border-top:1px solid var(--border-color);padding:12px max(16px,env(safe-area-inset-right)) calc(12px + env(safe-area-inset-bottom));z-index:100}
      .dp-bottom-inner {max-width:1030px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:12px}
      .dp-actions {display:flex;gap:8px}.dp-empty {text-align:center;padding:40px 20px}
      .dp-history {margin:12px 0}.dp-row input {width:100%}.dp-state {overflow-wrap:anywhere}.dp-state a {display:block;min-height:44px;padding-top:8px;text-decoration:underline}
      .daily-production button:focus-visible,.daily-production input:focus-visible {outline:2px solid var(--primary);outline-offset:2px}
      @media(max-width:640px){.dp-bottom{left:0;right:0}.dp-warehouses{grid-template-columns:1fr;gap:12px}.dp-context{grid-template-columns:1fr 1fr}.dp-station{grid-column:1/-1}.dp-add{grid-template-columns:1fr 100px}.dp-item-picker{grid-column:1/-1}.dp-row{grid-template-columns:1fr 110px;gap:12px}.dp-row .dp-state{grid-column:1}.dp-remove{grid-column:2;justify-self:end}.dp-actions{flex-wrap:wrap}.dp-bottom-inner{align-items:center}.dp-empty{padding:24px 12px}.dp-bottom-inner{display:grid;grid-template-columns:1fr;gap:8px}.dp-actions{display:grid;grid-template-columns:1fr 1.4fr}.dp-summary{font-size:14px}.daily-production{padding-bottom:160px}}
      .dp-settings-bar{display:none}.dp-field-error:empty{display:none}.dp-field-error{color:var(--dp-danger-color,var(--red-600,#b42318));font-size:13px;line-height:1.4;margin-top:6px;overflow-wrap:anywhere}.daily-production [aria-invalid="true"]{border:1px solid var(--dp-danger-color,var(--red-600,#b42318))}
      .dp-table-wrap{border:1px solid var(--border-color);border-radius:12px;overflow:clip;background:var(--card-bg);margin-bottom:12px}.dp-table{width:100%;table-layout:fixed;border-collapse:collapse}.dp-table th{position:sticky;top:48px;z-index:2;font-size:13px;color:var(--text-muted);font-weight:600;text-align:left;padding:10px 12px;background:var(--subtle-fg,var(--card-bg));border-bottom:1px solid var(--border-color)}.dp-table .dp-row{display:table-row;border:0;border-radius:0;margin:0;padding:0}.dp-table td{padding:8px 12px;vertical-align:middle;border-bottom:1px solid var(--border-color)}.dp-table tbody tr:last-child td{border-bottom:0}.dp-table .dp-quantity-col{width:150px}.dp-table .dp-state-col{width:200px}.dp-table .dp-action-col{width:72px}.dp-table .dp-qty-label{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.dp-table .dp-row-error td{padding-top:0}.dp-table .dp-state a{min-height:44px}.dp-table .dp-remove{width:48px}.dp-table .dp-meta{margin-top:2px}.dp-table .dp-row-name{line-height:1.35}
      .dp-review-dialog .modal-body{overscroll-behavior:contain}.dp-review-dialog .modal-dialog{margin:16px auto}.dp-review-dialog .modal-content{overflow:hidden;display:flex;flex-direction:column;max-height:calc(100dvh - 32px)}.dp-review-dialog .modal-header,.dp-review-dialog .modal-footer{flex-shrink:0}.dp-review-dialog .modal-body{min-height:0;overflow-y:auto;max-height:none}.dp-review-dialog .dp-blockers{border-left:3px solid var(--dp-danger-color,var(--red-600,#b42318));padding-left:12px;margin-bottom:20px}.dp-blockers h4{margin-top:0}.dp-blocker-group{margin-top:12px}.dp-blocker-list{padding-left:18px;margin:6px 0 0}.dp-blocker-list li{margin-bottom:10px;line-height:1.4}.dp-blocker-reasons{font-size:13px;color:var(--dp-danger-color,var(--red-600,#b42318));margin-top:3px}.dp-blocker-numbers{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--text-color);margin-top:4px}.dp-review-context{font-size:13px;color:var(--text-muted);line-height:1.6;margin-bottom:16px}
      @media(max-width:640px){.dp-settings{border:1px solid var(--border-color);border-radius:12px;padding:12px;margin-bottom:16px;background:var(--card-bg)}.dp-settings-bar{display:flex;align-items:center;gap:12px;justify-content:space-between}.dp-settings-summary{min-width:0;font-size:14px;overflow-wrap:anywhere}.dp-settings-summary small{display:block;color:var(--text-muted);margin-top:4px;font-size:12px}.dp-settings-toggle{flex-shrink:0}.dp-settings.is-collapsed .dp-settings-fields{display:none}.dp-settings:not(.is-collapsed) .dp-settings-fields{padding-top:12px}.dp-settings .dp-context{padding:0;border:0;border-radius:0}.dp-settings .dp-warehouses{margin-bottom:0}.dp-table-wrap{border:0;background:transparent;overflow:visible}.dp-table,.dp-table tbody{display:block;width:100%}.dp-table thead,.dp-table colgroup{display:none}.dp-table .dp-row{display:grid;grid-template-columns:minmax(0,1fr) 110px;gap:12px;border:1px solid var(--border-color);border-radius:12px;margin-bottom:12px;padding:16px;background:var(--card-bg)}.dp-table td{display:block;border:0;padding:0;min-width:0}.dp-table .dp-qty-label{position:static;width:auto;height:auto;clip:auto;white-space:normal;margin-bottom:6px}.dp-table .dp-state{grid-column:1}.dp-table .dp-action-cell{grid-column:2;justify-self:end}.dp-table .dp-row-error{display:block;margin:-4px 0 12px;padding:12px 16px;border:1px solid var(--border-color);border-radius:12px;background:var(--card-bg)}.dp-table .dp-row-error td{padding:0}.dp-blocker-numbers{gap:8px}}
    </style>
    <div class="dp-top-status"><span class="indicator-pill gray dp-status-pill" role="status" aria-live="polite">${__('Loading')}</span></div>
    <p>${__('Record completed production. Materials are calculated automatically from the approved BOM.')}</p>
    <section class="dp-settings"><div class="dp-settings-bar"><div class="dp-settings-summary"></div><button class="btn btn-default dp-settings-toggle" type="button" aria-expanded="true" aria-controls="dp-settings-fields">${__('Change')}</button></div><div class="dp-settings-fields" id="dp-settings-fields">
    <div class="dp-context">
      <div class="dp-station"></div>
      <div><label for="dp-date">${__('Production date')}</label><input id="dp-date" class="form-control" type="date"><div class="dp-field-error dp-date-error" id="dp-date-error"></div></div>
      <div><label for="dp-shift">${__('Shift / run (optional)')}</label><input id="dp-shift" class="form-control" maxlength="140"></div>
    </div>
    <div class="dp-warehouses"><div class="dp-source"></div><div class="dp-target"></div></div>
    </div></section>
    <div class="dp-feedback" role="status" aria-live="polite"></div>
    <div class="dp-add">
      <div class="dp-item-picker"></div>
      <div><label for="dp-add-qty">${__('Produced quantity')}</label><input id="dp-add-qty" class="form-control" type="number" inputmode="decimal" min="0" step="any"><div class="dp-field-error dp-add-qty-error" id="dp-add-qty-error"></div></div>
      <button class="btn btn-primary dp-add-button">${__('Add & next')}</button>
    </div>
    <div class="dp-rows"></div>
    <div class="dp-history"><button class="btn btn-default dp-history-button">${__('Today’s entries')}</button></div>
    <div class="dp-bottom"><div class="dp-bottom-inner"><div class="dp-summary-line"><span class="dp-summary"></span><span class="dp-save-status" role="status" aria-live="polite"></span></div><div class="dp-actions"><button class="btn btn-default dp-save">${__('Save draft')}</button><button class="btn btn-primary dp-review">${__('Review production')}</button></div></div></div>`);
    this.station = frappe.ui.form.make_control({parent:this.root.find('.dp-station'),df:{fieldname:'station',fieldtype:'Link',options:'Production Station',label:__('Production station'),reqd:1,get_query:()=>({filters:{enabled:1}}),change:()=>this.stationChanged()},render_input:true});
    const warehouseControl=(selector,fieldname,label)=>frappe.ui.form.make_control({parent:this.root.find(selector),df:{fieldname,fieldtype:'Link',options:'Warehouse',label:__(label),reqd:1,get_query:()=>({filters:{company:this.stationConfig?.company||this.doc?.company||'__select_station__',is_group:0,disabled:0}}),change:()=>this.warehouseChanged()},render_input:true});
    this.sourceWarehouse=warehouseControl('.dp-source','source_warehouse','Source warehouse');
    this.targetWarehouse=warehouseControl('.dp-target','target_warehouse','Target warehouse');
    this.item = frappe.ui.form.make_control({parent:this.root.find('.dp-item-picker'),df:{fieldname:'item',fieldtype:'Link',options:'Item',label:__('Item name or code'),get_query:()=>({filters:{disabled:0,is_stock_item:1,has_variants:0}})},render_input:true});
    for(const name of ['station','source','target','item-picker'])this.root.find('.dp-'+name).append(`<div class="dp-field-error dp-${name}-error" id="dp-${name}-error"></div>`);
    this.root.find('#dp-date').val(frappe.datetime.get_today());
    this.root.on('click','.dp-settings-toggle',()=>{this.settingsCollapsed=!this.settingsCollapsed;this.renderSettings();});
    this.root.on('click','.dp-add-button',()=>this.add());
    this.root.on('keydown','#dp-add-qty',e=>{if(e.key==='Enter')this.add();});
    this.root.on('input','.dp-item-picker input,#dp-add-qty',()=>this.clearFieldErrors());
    this.root.on('input','#dp-date,#dp-shift',()=>{this.clearFieldErrors();this.changed();this.renderSettings();});
    this.root.on('input','.dp-qty',e=>{this.doc.items[Number(e.target.dataset.index)].qty=Number(e.target.value);this.clearFieldErrors();this.changed();});
    this.root.on('click','.dp-remove',e=>{this.doc.items.splice(Number(e.currentTarget.dataset.index),1);this.changed();this.renderRows();});
    this.root.on('click','.dp-paste',()=>this.paste());
    this.root.on('click','.dp-save',()=>this.save());
    this.root.on('click','.dp-review',()=>this.review());
    this.root.on('click','.dp-new',()=>this.startNew());
    this.root.on('click','.dp-history-button',()=>{frappe.route_options={posting_date:frappe.datetime.get_today()};frappe.set_route('List','Daily Production');});
  }
  feedback(text,error=false){
    this.root.find('.dp-feedback').attr('role',error?'alert':'status').attr('aria-live',error?'assertive':'polite').text(error?text:'').toggleClass('dp-error',error);
    this.root.find('.dp-save-status').text(error?__('Needs attention'):text);
  }
  activate(){
    document.body.classList.add('dp-entry-active');
    document.scrollingElement.scrollTop=0;
    this.alignFooter();
  }
  alignFooter(){
    if(!this.root[0]?.getClientRects().length)return;
    const rect=this.root[0].getBoundingClientRect();
    this.root[0].style.setProperty('--dp-footer-left',`${Math.max(0,rect.left)}px`);
    this.root[0].style.setProperty('--dp-footer-right',`${Math.max(0,window.innerWidth-rect.right)}px`);
  }
  renderSettings(){
    const ready=Boolean(this.station?.get_value()&&this.sourceWarehouse?.get_value()&&this.targetWarehouse?.get_value());
    this.root.find('.dp-settings').toggleClass('is-collapsed',ready&&Boolean(this.settingsCollapsed));
    this.root.find('.dp-settings-toggle').attr('aria-expanded',String(!ready||!this.settingsCollapsed)).text(ready&&this.settingsCollapsed?__('Change'):__('Done'));
    const station=this.station?.get_value()||__('Production settings');
    const warehouses=ready?`${this.sourceWarehouse.get_value()} → ${this.targetWarehouse.get_value()}`:__('Choose a station and warehouses');
    this.root.find('.dp-settings-summary').html(`<strong>${this.esc(station)}</strong> · ${this.esc(this.root.find('#dp-date').val()||'')}<small>${this.esc(warehouses)}</small>`);
  }
  clearFieldErrors(){
    this.root.find('.dp-field-error').text('');
    this.root.find('[aria-invalid="true"]').removeAttr('aria-invalid aria-describedby');
  }
  fieldError(selector,message){
    const field=this.root.find(selector);field.attr('aria-invalid','true');
    const error=field.closest('.frappe-control').length?field.closest('.frappe-control').parent().find('.dp-field-error'):field.parent().find('.dp-field-error');
    if(error.length){error.attr('role','alert').text(message);if(error.attr('id'))field.attr('aria-describedby',error.attr('id'));}
    else this.feedback(message,true);
  }
  validateQuantities(){
    let valid=true;
    this.doc.items.forEach((row,index)=>{if(!Number.isFinite(Number(row.qty))||Number(row.qty)<=0){valid=false;this.fieldError(`#dp-qty-${index}`,__('Enter a quantity greater than zero.'));}});
    return valid;
  }
  async deleteDraft(){
    if(this.busy||this.loading||!this.doc?.name||this.doc.status!=='Draft')return;
    const name=this.doc.name;
    frappe.confirm(__('Delete draft {0}? This permanently removes the sheet and its unsaved changes. No stock will be posted.',[this.esc(name)]),async()=>{
      if(this.busy||this.loading||this.doc?.name!==name||this.doc.status!=='Draft')return;
      clearTimeout(this.saveTimer);this.busy=true;this.renderRows();
      try{
        await this.call(this.api+'delete_draft',{name});
        this.dirty=false;this.busy=false;
        await this.newSheet();this.feedback(__('Draft deleted'));
      }catch(e){this.feedback(__('Could not delete this draft. It may have changed or you may not have delete permission. Reopen the sheet before trying again.'),true);}
      finally{this.busy=false;this.renderRows();}
    });
  }
  startNew(){
    if(this.busy||this.loading)return;
    if(this.dirty||this.item.get_value()||this.root.find('#dp-add-qty').val())frappe.confirm(__('Discard unsaved changes?'),()=>this.newSheet());
    else this.newSheet();
  }
  rememberSheet(name){
    if(!window.location.protocol.startsWith('http')||!window.location.pathname.endsWith('/daily-production-entry'))return;
    const url=new URL(window.location.href);
    url.searchParams.delete('new_sheet');url.searchParams.delete('production_sheet');
    if(name)url.searchParams.set('sheet',name);else {url.searchParams.delete('sheet');url.searchParams.set('new_sheet','1');}
    window.history.replaceState(window.history.state,'',url);
  }
  async newSheet(){
    if(this.busy)return;
    const wasLoading=this.loading;this.loading=true;
    clearTimeout(this.poll);clearTimeout(this.saveTimer);
    this.rememberSheet(null);
    this.root.find('#dp-date').val(frappe.datetime.get_today());
    this.root.find('#dp-shift,#dp-add-qty').val('');
    this.applyingWarehouses=true;
    try {
      await this.item.set_value('');
      await this.sourceWarehouse.set_value(this.stationConfig?.source_warehouse||'');
      await this.targetWarehouse.set_value(this.stationConfig?.target_warehouse||'');
      this.doc={doctype:'Daily Production',items:[],status:'Draft',station:this.station.get_value(),company:this.stationConfig?.company,source_warehouse:this.sourceWarehouse.get_value(),target_warehouse:this.targetWarehouse.get_value()};
      this.settingsCollapsed=false;this.dirty=false;this.clearFieldErrors();this.feedback('');
    }finally{this.applyingWarehouses=false;this.loading=wasLoading;this.renderRows();}
  }
  async open(name){
    if(this.busy)return;
    clearTimeout(this.poll);clearTimeout(this.saveTimer);
    this.loading=true;this.root.find('input,button').prop('disabled',true);
    try {
    this.doc=await frappe.db.get_doc('Daily Production',name);
    await this.station.set_value(this.doc.station);await this.stationChanged();
    this.root.find('#dp-date').val(this.doc.posting_date);
    this.root.find('#dp-shift').val(this.doc.shift||'');
    this.settingsCollapsed=true;this.dirty=false;this.rememberSheet(this.doc.name);this.renderRows();this.feedback(__('Saved'));
    if(this.doc.status==='Queued')await this.refresh();
    } finally {this.loading=false;this.root.find('input,button').prop('disabled',false);if(this.doc)this.renderRows();}
  }
  async loadDraft(){
    try {
      if(frappe.route_options?.new_sheet || new URLSearchParams(window.location.search).get('new_sheet')){frappe.route_options=null;await this.newSheet();return;}
      const requested=frappe.route_options?.production_sheet||new URLSearchParams(window.location.search).get('sheet');
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
        await this.sourceWarehouse.set_value(restore&&this.doc.source_warehouse?this.doc.source_warehouse:station.source_warehouse);
        await this.targetWarehouse.set_value(restore&&this.doc.target_warehouse?this.doc.target_warehouse:station.target_warehouse);
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
        for(const [code,quantity] of rows){const item=await frappe.db.get_doc('Item',code);additions.push({doctype:'Daily Production Item',item_code:code,item_name:item.item_name,uom:item.stock_uom,qty:Number(quantity),status:'Pending'});}
        this.doc.items.push(...additions);dialog.hide();this.changed();this.renderRows();
      }catch(e){frappe.msgprint(this.esc(e.message||__('Could not load items. Check the pasted codes.')));}
      finally{this.busy=false;this.renderRows();}
    }});dialog.show();
  }
  async add(){
    if(this.busy||this.doc?.status!=='Draft')return;
    const code=this.item.get_value(),qty=Number(this.root.find('#dp-add-qty').val());
    this.clearFieldErrors();
    if(!code)this.fieldError('.dp-item-picker input',__('Select an item.'));
    if(!Number.isFinite(qty)||qty<=0)this.fieldError('#dp-add-qty',__('Enter a quantity greater than zero.'));
    if(!code||!Number.isFinite(qty)||qty<=0){this.feedback(__('Check the highlighted entry fields.'),true);return;}
    if(this.doc.items.some(r=>r.item_code===code)){this.fieldError('.dp-item-picker input',__('Already on this sheet. Edit its quantity below.'));return;}
    if(this.doc.items.length>=100){this.feedback(__('Maximum 100 rows per sheet.'),true);return;}
    this.busy=true;
    try {const item=await frappe.db.get_doc('Item',code);this.doc.items.push({doctype:'Daily Production Item',item_code:code,item_name:item.item_name,uom:item.stock_uom,qty,status:'Pending'});await this.item.set_value('');this.root.find('#dp-add-qty').val('');this.changed();this.renderRows();this.item.$input.focus();}
    catch(e){this.feedback(__('Could not add the item. Check the item code and connection, then retry.'),true);}
    finally{this.busy=false;this.renderRows();}
  }
  renderRows(){
    this.deleteDraftMenu?.toggle(Boolean(this.doc?.name&&this.doc.status==='Draft'&&!this.busy&&!this.loading));
    const editable=this.doc.status==='Draft';
    const statusColor={'Draft':'gray','Queued':'blue','Posted':'green','Partially Posted':'orange','Failed':'red'}[this.doc.status]||'gray';
    this.root.find('.dp-status-pill').attr('class',`indicator-pill ${statusColor} dp-status-pill`).text(__(this.doc.status));
    this.renderSettings();this.alignFooter();
    const rows=this.doc.items.map((r,i)=>`<tr class="dp-row"><td><div class="dp-row-name">${this.esc(r.item_name||r.item_code)}</div><div class="dp-meta">${this.esc(r.item_code)} · ${this.esc(r.uom||'')}</div></td><td><label class="dp-qty-label" for="dp-qty-${i}">${__('Quantity')}<span class="sr-only"> — ${this.esc(r.item_code)}</span></label><input id="dp-qty-${i}" class="form-control dp-qty" data-index="${i}" type="number" inputmode="decimal" step="any" min="0" value="${this.esc(r.qty)}" ${editable?'':'disabled'}><div class="dp-field-error" id="dp-qty-error-${i}"></div></td><td class="dp-state">${this.esc(r.status||'Pending')}${r.stock_entry?`<a href="${this.esc(frappe.utils.get_form_link('Stock Entry',r.stock_entry))}">${this.esc(r.stock_entry)}</a>`:''}</td><td class="dp-action-cell">${editable?`<button class="btn btn-default dp-remove" data-index="${i}" aria-label="${this.esc(__('Remove {0}',[r.item_code]))}">×</button>`:''}</td></tr>${r.error?`<tr class="dp-error dp-row-error"><td colspan="4">${this.esc(this.errorMessage(r.error))}</td></tr>`:''}`).join('');
    this.root.find('.dp-rows').html(this.doc.items.length?`<div class="dp-table-wrap"><table class="dp-table" aria-label="${__('Production items')}"><colgroup><col><col class="dp-quantity-col"><col class="dp-state-col"><col class="dp-action-col"></colgroup><thead><tr><th scope="col">${__('Item')}</th><th scope="col">${__('Produced quantity')}</th><th scope="col">${__('Status')}</th><th scope="col"><span class="sr-only">${__('Actions')}</span></th></tr></thead><tbody>${rows}</tbody></table></div>`:`<div class="dp-empty"><strong>${__('Start with an item and quantity')}</strong><p class="dp-meta">${__('Add each completed item. You can post one item now or several together.')}</p></div>`);
    this.root.find('.dp-summary').text(`${this.doc.items.length} ${this.doc.items.length===1?__('item'):__('items')}`);
    this.root.find('.dp-add,.dp-paste').toggle(editable);
    this.root.find('.dp-save').toggle(editable);
    this.root.find('.dp-review').prop('disabled',this.loading||this.busy||this.doc.status==='Posted'||!this.doc.items.length);
    this.root.find('#dp-date,#dp-shift').prop('disabled',!editable);
    this.station.$input.prop('disabled',!editable);
    this.sourceWarehouse.$input.prop('disabled',!editable);this.targetWarehouse.$input.prop('disabled',!editable);
    this.root.find('.dp-review').text(this.doc.status==='Posted'?__('Production posted'):this.doc.status==='Queued'?__('Check / resume posting'):this.doc.status==='Draft'?__('Review production'):__('Review failed rows'));
  }
  async save(){
    clearTimeout(this.saveTimer);
    if(this.busy||!this.doc||this.doc.status!=='Draft')return false;
    this.clearFieldErrors();
    const required=[['.dp-station input',this.station.get_value(),__('Choose a production station.')],['.dp-source input',this.sourceWarehouse.get_value(),__('Choose a source warehouse.')],['.dp-target input',this.targetWarehouse.get_value(),__('Choose a target warehouse.')]];
    if(required.some(([,value])=>!value)){this.settingsCollapsed=false;this.renderSettings();required.forEach(([selector,value,message])=>{if(!value)this.fieldError(selector,message);});this.feedback(__('Complete the highlighted production settings.'),true);return false;}
    if(!this.doc.items.length){this.fieldError('.dp-item-picker input',__('Add at least one item to this sheet.'));return false;}
    if(!this.root.find('#dp-date').val()){this.settingsCollapsed=false;this.renderSettings();this.fieldError('#dp-date',__('Choose a production date.'));return false;}
    if(!this.validateQuantities()){this.feedback(__('Check the highlighted quantities.'),true);return false;}
    const active=typeof document!=='undefined'?document.activeElement:null;
    const restoreId=active?.id&&this.root[0]?.contains(active)?active.id:null;
    this.busy=true;this.root.find('input,button').prop('disabled',true);this.feedback(__('Saving…'));
    try {
      this.doc.source_warehouse=this.sourceWarehouse.get_value();this.doc.target_warehouse=this.targetWarehouse.get_value();
      this.doc.station=this.station.get_value();this.doc.posting_date=this.root.find('#dp-date').val();this.doc.shift=this.root.find('#dp-shift').val();this.doc.posting_time=this.doc.posting_time||frappe.datetime.now_time();
      const saved=await this.call('frappe.client.save',{doc:this.doc});
      this.doc=saved;this.dirty=false;this.rememberSheet(saved.name);this.feedback(__('Saved'));this.renderRows();return true;
    }catch(e){this.feedback(__('Not saved. Your changes remain on this screen. Check the connection and retry.'),true);return false;}
    finally{this.busy=false;this.root.find('input,button').prop('disabled',false);this.renderRows();if(restoreId&&this.root[0]?.getClientRects().length)document.getElementById(restoreId)?.focus({preventScroll:true});}
  }
  async review(){
    if(this.busy)return;
    if(this.doc.status==='Draft'&&(this.item.get_value()||this.root.find('#dp-add-qty').val())){this.feedback(__('An item is still in the entry fields. Add it to the sheet or clear those fields before reviewing.'),true);return;}
    if(this.doc.status==='Draft'&&(!this.doc.name||this.dirty)&&!await this.save())return;
    if(!this.doc.name)return;
    this.busy=true;
    try {
      const result=await this.call(this.api+'review',{name:this.doc.name});
      this.reviewToken=result.review_token;
      const shortage=result.shortages.length>0;
      const missing=result.valuation_issues||[];
      const materialNames=new Map(result.rows.flatMap(row=>row.materials.map(m=>[m.item_code,m.item_name])));
      const groups=new Map();
      const getIssue=(m)=>{if(!groups.has(m.warehouse))groups.set(m.warehouse,new Map());const items=groups.get(m.warehouse);if(!items.has(m.item_code))items.set(m.item_code,{...m,item_name:m.item_name||materialNames.get(m.item_code)});return items.get(m.item_code);};
      missing.forEach(m=>{getIssue(m).missingCost=true;});
      result.shortages.forEach(m=>{Object.assign(getIssue(m),m,{shortage:true});});
      const blocked=groups.size>0;
      const issues=Array.from(groups.values()).reduce((sum,items)=>sum+items.size,0);
      const blockers=blocked?`<section class="dp-blockers" role="region" aria-label="${__('Posting blocked')}"><h4>${__('Posting blocked')} · ${issues} ${issues===1?__('material'):__('materials')}</h4><p>${__('Resolve the material issues below, then review again.')}</p>${Array.from(groups,([warehouse,items])=>`<div class="dp-blocker-group"><div class="dp-missing-warehouse">${__('Source warehouse')}: <strong>${this.esc(warehouse)}</strong></div><ul class="dp-blocker-list">${Array.from(items.values(),m=>`<li><strong>${this.esc(m.item_code)}</strong>${m.item_name?` — ${this.esc(m.item_name)}`:''}<div class="dp-blocker-reasons">${[m.missingCost?__('Missing valuation'):null,m.shortage?__('Insufficient stock'):null].filter(Boolean).join(' · ')}</div>${m.shortage?`<div class="dp-blocker-numbers"><span>${__('Required')}: <strong>${this.esc(m.required)}</strong></span><span>${__('Available')}: <strong>${this.esc(m.available)}</strong></span><span>${__('Shortage')}: <strong>${this.esc(Number(Math.max(0,m.required-m.available).toFixed(6)))}</strong></span></div>`:''}</li>`).join('')}</ul></div>`).join('')}<small>${__('Add valid material costs, replenish the source warehouse, or reduce quantities as applicable.')}</small></section>`:'';
      const dialog=new frappe.ui.Dialog({title:__('Review production'),fields:[{fieldname:'summary',fieldtype:'HTML'}],primary_action_label:blocked?__('Back to sheet'):__('Post production'),primary_action:async()=>{dialog.hide();if(!blocked)await this.post();}});
      dialog.fields_dict.summary.$wrapper.html(`${blockers}<div class="dp-review-context">${this.esc(this.doc.station)} · ${this.esc(this.doc.posting_date)}<br>${__('Source')}: ${this.esc(this.doc.source_warehouse)}<br>${__('Target')}: ${this.esc(this.doc.target_warehouse)}</div>${result.rows.map(r=>`<p><strong>${this.esc(r.item_code)} — ${this.esc(r.qty)} ${this.esc(r.uom||'')}</strong><br><small>${this.esc(r.bom_no)}</small></p><details><summary>${__('Calculated materials')}</summary>${r.materials.map(m=>`<p>${this.esc(m.item_name||m.item_code)}: ${this.esc(m.qty)} ${this.esc(m.uom)}</p>`).join('')}</details>`).join('')}`);
      dialog.$wrapper.addClass('dp-review-dialog');
      dialog.show();
    }catch(e){this.feedback(__('Could not review production. Check the message above and retry.'),true);}
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
    this.doc=await frappe.db.get_doc('Daily Production',this.doc.name);this.renderRows();
    if(this.doc.status==='Queued')this.poll=setTimeout(()=>this.refresh().catch(()=>this.feedback(__('Connection lost. Reopen the saved sheet to check posting status.'),true)),2500);
    else if(this.doc.status==='Draft')this.feedback(__('Saved'));
    else this.feedback(`${this.doc.status} · ${this.doc.items.filter(r=>r.status==='Posted').length}/${this.doc.items.length} ${__('entries posted')}`);
  }
}
