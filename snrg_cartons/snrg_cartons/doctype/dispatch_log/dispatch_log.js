frappe.ui.form.on('Dispatch Log CTN', {
    carton_id: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.carton_id) {
            frappe.db.get_doc('Carton Box Log', row.carton_id).then(cbl => {
                let summary = (cbl.items || [])
                    .map(i => `${i.item_code} × ${i.qty}`)
                    .join(', ');
                frappe.model.set_value(cdt, cdn, 'box_type', cbl.box_type);
                frappe.model.set_value(cdt, cdn, 'packed_date', cbl.packed_date);
                frappe.model.set_value(cdt, cdn, 'items_summary', summary);
                frappe.model.set_value(cdt, cdn, 'gross_weight_kg', cbl.gross_weight_kg);
                frm.trigger('calculate_totals');
            });
        }
    }
});

frappe.ui.form.on('Dispatch Log', {
    sales_order: function(frm) {
        if (frm.doc.sales_order) {
            frappe.db.get_value("Sales Order", frm.doc.sales_order, ["customer", "customer_address"], function(value) {
                if (value && value.customer) frm.set_value("customer", value.customer);
                if (value && value.customer_address) frm.set_value("customer_address", value.customer_address);
            });
        }
    },
    calculate_totals: function(frm) {
        let total_cartons = (frm.doc.cartons || []).length;
        let total_weight = (frm.doc.cartons || [])
            .reduce((s, r) => s + (r.gross_weight_kg || 0), 0);
        frm.set_value('total_cartons', total_cartons);
        frm.set_value('total_gross_weight', parseFloat(total_weight.toFixed(2)));
        // total_pieces requires fetching all carton items — handle server side on save
    }
});
