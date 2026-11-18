// Read-only: never changes PO prices, fields, workflow or approval rules.
frappe.ui.form.on('Purchase Order', {
    refresh(frm) {
        frm.add_custom_button(__('Compare Purchase Rates'), async () => {
            if (!frm.doc.company || !frm.doc.supplier) {
                frappe.msgprint(__('Select the company and supplier first.'));
                return;
            }
            if (frm.cscript.calculate_taxes_and_totals) frm.cscript.calculate_taxes_and_totals();
            const {message: rows} = await frappe.call({
                method: 'snrg_supplychain.supply_chain.purchasing.compare_purchase_rates',
                args: {document: frm.doc}, freeze: true,
                freeze_message: __('Comparing previous purchase rates…')
            });
            const esc = value => frappe.utils.escape_html(String(value ?? ''));
            const money = value => value == null ? '—' : esc(format_number(value, null, 4));
            const body = (rows || []).map(row => `<tr>
                <td>${esc(row.idx)}</td><td>${esc(row.item_code)}</td><td>${esc(row.stock_uom)}</td>
                <td>${money(row.current_rate)}</td><td>${money(row.previous_rate)}</td>
                <td class="${row.variance > 0 ? 'text-danger' : ''}">${row.variance == null ? '—' : `${row.variance > 0 ? '+' : ''}${esc(format_number(row.variance, null, 2))}%`}</td>
                <td>${row.previous_po ? `<a href="/app/purchase-order/${encodeURIComponent(row.previous_po)}">${esc(row.previous_po)}</a><br>${esc(row.previous_date)}` : __('No comparable purchase history')}</td>
                </tr>`).join('');
            const dialog = new frappe.ui.Dialog({title: __('Purchase Rate Comparison'), size: 'extra-large', fields: [{fieldname: 'comparison', fieldtype: 'HTML'}]});
            dialog.fields_dict.comparison.$wrapper.html(`<p>${__('Same supplier and company. Rates are after discounts, before tax, in company currency per stock UOM. Multiple matching lines in the previous PO are quantity-weighted.')}</p>
                <div class="table-responsive"><table class="table table-bordered"><thead><tr>
                <th>#</th><th>${__('Item')}</th><th>${__('Stock UOM')}</th><th>${__('Current Rate')}</th><th>${__('Previous Rate')}</th><th>${__('Change')}</th><th>${__('Previous PO')}</th>
                </tr></thead><tbody>${body}</tbody></table></div>`);
            dialog.show();
        });
        frm.add_custom_button(__('Overdue Supplier Deliveries'), () => frappe.set_route('query-report', 'Overdue Supplier Deliveries', {company: frm.doc.company}));
    }
});
