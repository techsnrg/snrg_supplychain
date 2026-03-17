frappe.ui.form.on('Carton Box Log', {
    box_type: function(frm) {
        if (frm.doc.box_type) {
            frappe.db.get_doc('Carton Box Type', frm.doc.box_type)
            .then(doc => {
                frm.set_value('dimensions', `${doc.length_cm} × ${doc.width_cm} × ${doc.height_cm} cm`);
                frm.set_value('empty_weight_kg', doc.empty_weight_kg);
                frm.trigger('calculate_gross_weight');
            });
        }
    },
    calculate_gross_weight: function(frm) {
        // net_weight_kg = sum of (item qty × item_weight_kg) from child table
        // gross_weight_kg = net_weight_kg + empty_weight_kg
        let net = 0;
        (frm.doc.items || []).forEach(row => {
            net += (row.qty || 0) * (row.item_weight_kg || 0);
        });
        frm.set_value('net_weight_kg', net);
        frm.set_value('gross_weight_kg', net + (frm.doc.empty_weight_kg || 0));
    }
});

// When item_code is selected in child table → fetch item name, UOM, weight
frappe.ui.form.on('Carton Box Log Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code) {
            frappe.db.get_doc('Item', row.item_code).then(item => {
                frappe.model.set_value(cdt, cdn, 'item_name', item.item_name);
                frappe.model.set_value(cdt, cdn, 'uom', item.stock_uom);
                frappe.model.set_value(cdt, cdn, 'item_weight_kg', item.weight_per_unit || 0);
                frm.trigger('calculate_gross_weight');
            });
        }
    },
    qty: function(frm) { frm.trigger('calculate_gross_weight'); }
});
