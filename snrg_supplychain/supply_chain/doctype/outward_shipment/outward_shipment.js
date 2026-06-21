frappe.ui.form.on('Outward Shipment Carton', {
    carton_id: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.carton_id) {
            frappe.db.get_doc('Packed Carton', row.carton_id).then(cbl => {
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

frappe.ui.form.on('Outward Shipment', {
    refresh: function(frm) {
        // Add Carton button on draft/unsaved shipments
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Add Carton'), () => {
                show_add_carton_dialog(frm);
            }).addClass('btn-primary');
        }

        // Freight quote button on submitted outward shipments
        if (frm.doc.docstatus === 1) {
            if (frm.doc.freight_quotation) {
                frm.add_custom_button(__('View Freight Quote'), function() {
                    frappe.set_route('Form', 'Freight Quotation', frm.doc.freight_quotation);
                }, __('Freight'));
            } else {
                frm.add_custom_button(__('Get Freight Quote'), function() {
                    frappe.call({
                        method: 'snrg_supplychain.supply_chain.doctype.freight_quotation.freight_quotation.create_from_dispatch',
                        args: { dispatch_log: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Creating Freight Quotation...'),
                        callback(r) {
                            if (!r.exc && r.message) {
                                frappe.set_route('Form', 'Freight Quotation', r.message);
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Freight'));
            }

            // Show freight summary if finalized
            if (frm.doc.selected_transporter && frm.doc.freight_amount) {
                frm.dashboard.set_headline_alert(
                    `<span class="indicator green">Freight: <strong>${frm.doc.selected_transporter}</strong> — ₹${frappe.format(frm.doc.freight_amount, {fieldtype: 'Currency'})}</span>`
                );
            }
        }
    },

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
            frappe.db.get_doc("Sales Order", frm.doc.sales_order).then(so => {
                // Set customer
                frm.set_value("customer", so.customer);
            });
        } else {
            frm.set_value("customer", "");
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
        let item_map = {};
        let promises = [];

        (frm.doc.cartons || []).forEach(row => {
            if (row.carton_id) {
                promises.push(
                    frappe.db.get_doc('Packed Carton', row.carton_id).then(cbl => {
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


// ── Add Carton Dialog ──────────────────────────────────────────────────────

function reset_carton_and_focus(d) {
    d.set_value('carton_id', '');
    d.set_value('box_type', '');
    d.set_value('packed_date', '');
    d.set_value('gross_weight_kg', 0);
    d.set_value('items_preview', '');
    setTimeout(() => {
        let $input = d.fields_dict.carton_id && d.fields_dict.carton_id.$input;
        if ($input) {
            $input.val('');
            $input.trigger('input');
            $input.focus();
        }
    }, 80);
}

function show_add_carton_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Add Carton to Shipment'),
        fields: [
            {
                fieldname: 'carton_id',
                fieldtype: 'Link',
                label: __('Carton ID'),
                options: 'Packed Carton',
                reqd: 1,
                get_query: () => ({ filters: { status: 'Available' } }),
                onchange: function() {
                    let carton_id = d.get_value('carton_id');
                    if (!carton_id) return;
                    frappe.db.get_doc('Packed Carton', carton_id).then(cbl => {
                        let preview = (cbl.items || [])
                            .map(i => `${i.item_code} × ${parseInt(i.qty)} ${i.uom}`)
                            .join('\n');
                        d.set_value('box_type', cbl.box_type || '');
                        d.set_value('packed_date', cbl.packed_date || '');
                        d.set_value('gross_weight_kg', cbl.gross_weight_kg || 0);
                        d.set_value('items_preview', preview || '(no items)');
                    });
                }
            },
            {
                fieldtype: 'Column Break'
            },
            {
                fieldname: 'gross_weight_kg',
                fieldtype: 'Float',
                label: __('Gross Weight (kg)'),
                read_only: 1
            },
            {
                fieldname: 'box_type',
                fieldtype: 'Data',
                label: __('Box Type'),
                read_only: 1
            },
            {
                fieldname: 'packed_date',
                fieldtype: 'Date',
                label: __('Packed Date'),
                read_only: 1
            },
            {
                fieldtype: 'Section Break',
                label: __('Contents')
            },
            {
                fieldname: 'items_preview',
                fieldtype: 'Small Text',
                label: __('Items'),
                read_only: 1
            }
        ],
        primary_action_label: __('Add to Shipment'),
        primary_action: function(values) {
            if (!values.carton_id) {
                frappe.show_alert({ message: __('Please select a Carton first.'), indicator: 'orange' }, 3);
                reset_carton_and_focus(d);
                return;
            }

            // Check for duplicates
            let already_added = (frm.doc.cartons || []).find(r => r.carton_id === values.carton_id);
            if (already_added) {
                frappe.show_alert({
                    message: __(`${values.carton_id} is already in this shipment.`),
                    indicator: 'orange'
                }, 3);
                reset_carton_and_focus(d);
                return;
            }

            let summary = (d.get_value('items_preview') || '').replace(/\n/g, ', ');
            frm.add_child('cartons', {
                carton_id: values.carton_id,
                box_type: values.box_type || '',
                packed_date: values.packed_date || '',
                gross_weight_kg: values.gross_weight_kg || 0,
                items_summary: summary
            });
            frm.refresh_field('cartons');
            frm.trigger('calculate_totals');
            frm.trigger('rebuild_items_summary');

            frappe.show_alert({
                message: __(`${values.carton_id} added`),
                indicator: 'green'
            }, 3);

            reset_carton_and_focus(d);
        },
        secondary_action_label: __('Done'),
        secondary_action: function() { d.hide(); }
    });

    // Prevent Escape from closing dialog
    d.$wrapper.on('keydown.add-carton-dialog', function(e) {
        if (e.key === 'Escape') e.stopPropagation();
    });

    d.show();
    setTimeout(() => reset_carton_and_focus(d), 300);
}
