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
                frm.trigger('rebuild_items_summary');
            });
        }
    },
    cartons_remove: function(frm) {
        frm.trigger('calculate_totals');
        frm.trigger('rebuild_items_summary');
    }
});

frappe.ui.form.on('Dispatch Log', {
    setup: function(frm) {
        frm.set_query("carton_id", "cartons", function() {
            return {
                filters: {
                    status: "Available"
                }
            };
        });
    },
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
    },
    rebuild_items_summary: function(frm) {
        // Clear existing items summary
        frm.doc.dispatch_items = [];

        let item_map = {};
        let promises = [];

        (frm.doc.cartons || []).forEach(row => {
            if (row.carton_id) {
                promises.push(
                    frappe.db.get_doc('Carton Box Log', row.carton_id).then(cbl => {
                        (cbl.items || []).forEach(item => {
                            let key = item.item_code;
                            if (!item_map[key]) {
                                item_map[key] = {
                                    item_code: item.item_code,
                                    item_name: item.item_name,
                                    total_qty: 0,
                                    uom: item.uom,
                                    cartons: []
                                };
                            }
                            item_map[key].total_qty += (item.qty || 0);
                            if (!item_map[key].cartons.includes(row.carton_id)) {
                                item_map[key].cartons.push(row.carton_id);
                            }
                        });
                    })
                );
            }
        });

        Promise.all(promises).then(() => {
            frm.doc.dispatch_items = [];
            let total_pieces = 0;

            Object.values(item_map).forEach(item => {
                let child = frm.add_child('dispatch_items');
                child.item_code = item.item_code;
                child.item_name = item.item_name;
                child.total_qty = item.total_qty;
                child.uom = item.uom;
                child.from_cartons = item.cartons.join(', ');
                total_pieces += item.total_qty;
            });

            frm.set_value('total_pieces', total_pieces);
            frm.refresh_field('dispatch_items');
        });
    }
});
