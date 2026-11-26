/* Native Desk forms; all mutations are checked again by the server. */
(() => {
    const api = 'snrg_supplychain.returns.api.';
    async function showDraft(doctype, values) {
        if (values.existing) {frappe.set_route('Form', doctype, values.existing); return;}
        await frappe.new_doc(doctype, {}, doc => {
            const tables = frappe.get_meta(doctype).fields.filter(df => df.fieldtype === 'Table');
            const names = new Set(tables.map(df => df.fieldname));
            const audit = new Set(['doctype','name','docstatus','creation','modified','modified_by','owner','__islocal','__unsaved']);
            for (const [key,value] of Object.entries(values)) {
                if (!audit.has(key) && !names.has(key)) doc[key] = value;
            }
            for (const df of tables) {
                if (!values[df.fieldname]) continue;
                doc[df.fieldname] = [];
                for (const value of values[df.fieldname]) {
                    const row = frappe.model.add_child(doc, df.options, df.fieldname);
                    for (const [key,item] of Object.entries(value)) {
                        if (!audit.has(key) && !['parent','parenttype','parentfield','idx'].includes(key)) row[key] = item;
                    }
                }
            }
        });
    }
    async function draftReceipt(frm) {
        if (Number(frm.doc.native_returns_version)>=3) {
            const r=await frappe.call({method:api+'arrival_options',args:{authorization:frm.doc.name}});
            frappe.prompt([{fieldname:'choice',label:__('Native stock arrival'),fieldtype:'Select',options:r.message.map((x,i)=>({value:String(i),label:x.label})),reqd:1}],async v=>{
                const option=r.message[Number(v.choice)];
                const draft=await frappe.call({method:api+'stock_arrival',args:{authorization:frm.doc.name,doctype:option.doctype,source:option.source},freeze:true});
                await showDraft(option.doctype,draft.message);
            },__('Receive into Returns — Pending QC'),__('Create draft'));
            return;
        }
        const r = await frappe.call({method:api+'populate',args:{doctype:'Return Receipt',source:frm.doc.name},freeze:true});
        await showDraft('Return Receipt',r.message);
    }
    async function inspectReceipt(frm) {
        const choices=(frm.doc.items||[]).map(row=>({value:row.name,label:`${row.idx}. ${row.item_code} · ${row.received_qty} ${row.uom}`}));
        frappe.prompt([{fieldname:'row',label:__('Custody item'),fieldtype:'Select',options:choices,reqd:1}],async v=>{
            const r=await frappe.call({method:api+'populate',args:{doctype:'Quality Inspection',source:frm.doc.name,receipt_item:v.row},freeze:true});
            await showDraft('Quality Inspection',r.message);
        },__('Inspect received material'),__('Open native inspection'));
    }
    let settlementRole = 'Accounts Manager';
    async function loadApprovalRole() {
        const r = await frappe.call({method: api + 'approval_context'});
        settlementRole = r.message.settlement_role;
    }
    const can = roles => roles.some(role => frappe.user_roles.includes(role));
    frappe.ui.form.on('Material Return Authorization', {
        async refresh(frm) {
            await loadApprovalRole();
            if (frm.is_new()) return;
            if (['Authorized','Exceptions Approved','Finance Review'].includes(frm.doc.workflow_state) && can(['Stock User','Stock Manager']))
                frm.add_custom_button(__(Number(frm.doc.native_returns_version)>=3?'Receive into Returns warehouse':'Record custody receipt'),()=>draftReceipt(frm));
            if (Number(frm.doc.native_returns_version)>=3 && ['Authorized','Exceptions Approved'].includes(frm.doc.workflow_state) && can(['Stock User','Stock Manager']))
                frm.add_custom_button(__('Create return pickup'),()=>showDraft('Shipment',{
                    pickup_from_type:'Customer',pickup_customer:frm.doc.customer,delivery_to_type:'Company',delivery_company:frm.doc.company,
                    custom_return_mra:frm.doc.name,custom_return_direction:'Inward',description_of_content:'Material return against '+frm.doc.name,pickup_date:frappe.datetime.get_today()
                }));
            if (frm.doc.workflow_state==='Settlement Approved' && can(['Accounts User',settlementRole])) {
                frm.add_custom_button(__('Create native settlement document'),async()=>{
                    const r=await frappe.call({method:api+'native_document_options',args:{authorization:frm.doc.name}});
                    frappe.prompt([{fieldname:'choice',label:__('Document'),fieldtype:'Select',options:r.message.map((x,i)=>({value:String(i),label:x.label})),reqd:1}],async v=>{
                        const option=r.message[Number(v.choice)];
                        const draft=await frappe.call({method:api+'native_document',args:{authorization:frm.doc.name,doctype:option.doctype,invoice:option.invoice,update_stock:option.update_stock},freeze:true});
                        await showDraft(option.doctype,draft.message);
                    },__('Standard ERPNext document'),__('Create draft'));
                });
            }
            frm.add_custom_button(__('Customer return history'), async () => {
                const r = await frappe.call({method: api + 'customer_history', args: {
                    company: frm.doc.company, customer: frm.doc.customer, currency: frm.doc.currency}, freeze: true});
                const h = r.message, esc = frappe.utils.escape_html;
                const d = new frappe.ui.Dialog({title: __('Customer return history'), size: 'large', fields: [{fieldname: 'history', fieldtype: 'HTML'}]});
                d.fields_dict.history.$wrapper.html(`<p>${__('Purchases')}: ${esc(String(h.purchases))} ${esc(h.currency)} · ${__('Credit-note returns')}: ${esc(String(h.credited_returns))} · ${esc(h.return_percentage.toFixed(2))}%</p><p>${esc(h.note)}</p><table class="table"><thead><tr><th>MRA</th><th>Status</th><th>Category</th><th>Approved value</th></tr></thead><tbody>${h.authorizations.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.status)}</td><td>${esc(x.category_summary || '')}</td><td>${esc(String(x.approved_value))}</td></tr>`).join('')}</tbody></table>`);
                d.show();
            });
        },
        setup(frm) {
            frm.set_query('supplier',()=>({filters:{custom_is_customer:1,custom_linked_customer:frm.doc.customer,disabled:0}}));
            frm.set_query('return_warehouse',()=>({filters:{company:frm.doc.company,is_group:0,...(Number(frm.doc.native_returns_version)>=3?{custom_returns_quarantine:1}:{})}}));
            frm.set_query('sales_invoice', 'items', () => ({filters: {
                customer: frm.doc.customer, company: frm.doc.company, currency: frm.doc.currency, docstatus: 1, is_return: 0
            }}));
        },
        company: clearInvoiceReferences,
        customer: clearInvoiceReferences,
        currency: clearInvoiceReferences,
        route: fetchSupplier
    });
    function clearInvoiceReferences(frm) {
        if (!frm.is_new() && frm.doc.approved_by) return;
        for (const row of frm.doc.items || []) {
            Object.assign(row, {sales_invoice: null, sales_invoice_item: null, net_rate: 0, invoice_date: null, remaining_qty: 0, invoice_confirmed: 0, invoice_source: null});
        }
        frm.refresh_field('items');
    }
    function clearRow(cdt, cdn) {
        return frappe.model.set_value(cdt, cdn, {sales_invoice: null, sales_invoice_item: null, invoice_confirmed: 0, net_rate: 0, invoice_source: null});
    }
    async function chooseSale(frm, cdt, cdn, latest = false) {
        const row = locals[cdt][cdn];
        if (!frm.doc.company || !frm.doc.customer || !frm.doc.currency || !row.item_code || !row.uom) {
            frappe.msgprint(__('Choose company, customer, currency, item and UOM first.'));
            return;
        }
        let start = 0, choices = [];
        do {
            const r = await frappe.call({method: api + 'invoice_sales', freeze: true,
                freeze_message: __('Searching customer sales…'), args: {
                    company: frm.doc.company, customer: frm.doc.customer, currency: frm.doc.currency,
                    item_code: row.item_code, uom: row.uom, invoice: latest ? null : row.sales_invoice, start
                }});
            choices = choices.concat(r.message.rows);
            start = r.message.next_start;
        } while (start !== null && (latest ? choices.length === 0 : true));
        if (!choices.length) {
            if (!latest) {row.sales_invoice_item = null; row.invoice_confirmed = 0; frm.dirty(); frm.refresh_field('items');}
            frappe.msgprint(__('No eligible sale found. Valuation needs review; no fallback rate will be invented.'));
            return;
        }
        const options = choices.map((x, i) => ({label: `${x.sales_invoice} · ${x.invoice_date} · ${x.currency} ${x.net_rate} · Qty ${x.remaining_qty} · Line ${x.sales_invoice_item}`, value: String(i)}));
        frappe.prompt([{fieldname: 'sale', label: latest ? __('Confirm suggested invoice line') : __('Select invoice line'), fieldtype: 'Select', options, reqd: 1}], async v => {
            const selected = choices[Number(v.sale)];
            // Set invoice after its child reference to avoid an onchange lookup loop.
            Object.assign(row, selected, {invoice_source: latest ? 'Latest Sale Suggestion' : 'Manually Selected', invoice_confirmed: 1});
            frm.dirty(); frm.refresh_field('items');
        }, __('Invoice valuation'), __('Use this invoice'));
    }
    frappe.ui.form.on('MRA Item', {
        sales_invoice(frm, cdt, cdn) {if (locals[cdt][cdn].sales_invoice) chooseSale(frm, cdt, cdn);},
        item_code(frm, cdt, cdn) {return clearRow(cdt, cdn);},
        uom(frm, cdt, cdn) {return clearRow(cdt, cdn);},
        find_latest_sale(frm, cdt, cdn) {return chooseSale(frm, cdt, cdn, true);},
        view_earlier_sales(frm, cdt, cdn) {
            const row = locals[cdt][cdn]; const original = row.sales_invoice;
            row.sales_invoice = null;
            const task = chooseSale(frm, cdt, cdn, false); row.sales_invoice = original;
            return task;
        }
    });
    for (const dt of ['Delivery Note','Purchase Receipt','Stock Entry']) {
        frappe.ui.form.on(dt,{refresh(frm){
            if (!frm.doc.custom_return_mra || frm.doc.custom_return_purpose!=='Arrival') return;
            frm.set_intro(__('This native arrival posts inventory into Returns — Pending QC. Customer settlement follows inspection and does not post stock again.'));
            frm.add_custom_button(__('Open return case'),()=>frappe.set_route('Form','Material Return Authorization',frm.doc.custom_return_mra));
            if (frm.doc.docstatus!==1) return;
            if (can(['Quality Manager'])) frm.add_custom_button(__('Inspect arrived material'),()=>{
                frappe.prompt([{fieldname:'row',label:__('Receipt item'),fieldtype:'Select',options:frm.doc.items.map(x=>({value:x.name,label:`${x.idx}. ${x.item_code} · ${Math.abs(x.qty)}`})),reqd:1}],async v=>{
                    const r=await frappe.call({method:api+'arrival_inspection',args:{doctype:dt,name:frm.doc.name,receipt_item:v.row},freeze:true});
                    await showDraft('Quality Inspection',r.message);
                },__('Inspect native stock receipt'),__('Open inspection'));
            });
            if (can(['Stock User','Stock Manager'])) frm.add_custom_button(__('Move inspected stock'),async()=>{
                const r=await frappe.call({method:api+'disposition_options',args:{authorization:frm.doc.custom_return_mra}});
                frappe.prompt([{fieldname:'choice',label:__('QC quantity'),fieldtype:'Select',options:r.message.map((x,i)=>({value:String(i),label:x.label})),reqd:1},
                    {fieldname:'target',label:__('Destination warehouse (blank only for rejected goods leaving the company)'),fieldtype:'Link',options:'Warehouse',get_query:()=>({filters:{company:frm.doc.company,is_group:0,custom_returns_quarantine:0}})}],async v=>{
                        const selected=r.message[Number(v.choice)];
                        const draft=await frappe.call({method:api+'stock_disposition',args:{authorization:frm.doc.custom_return_mra,quality_inspection:selected.qi,allocation:selected.allocation,target_warehouse:v.target},freeze:true});
                        await showDraft(draft.message.doctype,draft.message);
                    },__('Native QC disposition'),__('Create draft'));
            });
            if (can(['Managing Director']) && frm.doc.custom_return_customer_disposal_instruction && !frm.doc.custom_return_disposal_approved_by)
                frm.add_custom_button(__('Approve disposal'),async()=>{await frappe.call({method:api+'approve_native_disposal',args:{doctype:dt,name:frm.doc.name},freeze:true});frm.reload_doc();});
        }});
    }
    frappe.ui.form.on('Return Receipt', {
        refresh(frm) {
            frm.set_intro(__('Historical custody document for earlier cases. New cases receive inventory through native stock documents.'));
            if (frm.is_new()) return;
            if (['Received','Disposal Approved'].includes(frm.doc.workflow_state) && can(['Quality Manager']))
                frm.add_custom_button(__('Inspect material'),()=>inspectReceipt(frm));
            frm.add_custom_button(__('Open return case'),()=>frappe.set_route('Form','Material Return Authorization',frm.doc.authorization));
            frm.add_custom_button(__('Create native Shipment'),()=>showDraft('Shipment',{
                pickup_from_type:'Customer',pickup_customer:frm.doc.customer,delivery_to_type:'Company',delivery_company:frm.doc.company,
                custom_return_mra:frm.doc.authorization,custom_return_receipt:frm.doc.name,custom_return_transporter:frm.doc.transporter,
                custom_return_direction:'Inward',description_of_content:'Material return against '+frm.doc.authorization,
                pickup_date:frappe.datetime.get_today()
            }));
        }
    });
    function qiQuery(frm) {
        if (frm.doc.reference_type==='Return Receipt') {
            frm.set_query('item_code',()=>({query:api+'custody_item_query',filters:{receipt:frm.doc.reference_name}}));
        } else {
            frm.set_query('item_code',()=>({query:'erpnext.stock.doctype.quality_inspection.quality_inspection.item_query',filters:{reference_doctype:frm.doc.reference_type,reference_name:frm.doc.reference_name,inspection_type:frm.doc.inspection_type}}));
        }
    }
    frappe.ui.form.on('Quality Inspection',{
        refresh(frm) {
            qiQuery(frm);
            if (frm.doc.custom_return_mra) {
                frm.set_intro(__('Native product-test result and commercial return acceptance are separate. Complete the quantity disposition below.'));
                frm.add_custom_button(__('Open return case'),()=>frappe.set_route('Form','Material Return Authorization',frm.doc.custom_return_mra));
            }
        },
        reference_type:qiQuery,
        reference_name:qiQuery
    });
    for (const dt of ['Return Inspection','Return Settlement']) {
        frappe.ui.form.on(dt,{refresh(frm){frm.set_intro(__('Read-only legacy evidence. New cases use native Quality Inspection and MRA settlement.'));}});
    }
    async function fetchSupplier(frm) {
        if (frm.doc.route !== 'Customer Invoice') {await frm.set_value('supplier', null); return;}
        if (!frm.doc.customer) return;
        const r = await frappe.call({method: api + 'linked_suppliers', args: {customer: frm.doc.customer}});
        if (r.message.length === 1) await frm.set_value('supplier', r.message[0].name);
        else frappe.msgprint(r.message.length ? __('Select the correct linked Supplier.') : __('Link an existing Supplier or create one with Is Also a Customer checked.'));
    }
})();
