frappe.ui.form.on('Carton Box Log', {

	refresh: function(frm) {
		// Add Item button — only on unsaved / draft forms
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Add Item'), () => {
				show_add_item_dialog(frm);
			}).addClass('btn-primary');
		}
	},

	box_type: function(frm) {
		if (frm.doc.box_type) {
			frappe.db.get_doc('Carton Box Type', frm.doc.box_type)
			.then(doc => {
				frm.set_value('dimensions', `${doc.length_in} × ${doc.width_in} × ${doc.height_in} in`);
				frm.set_value('empty_weight_g', doc.empty_weight_g);
				frm.trigger('calculate_gross_weight');
			});
		}
	},

	calculate_gross_weight: function(frm) {
		let net = 0;
		(frm.doc.items || []).forEach(row => {
			net += (row.qty || 0) * (row.item_weight_kg || 0);
		});
		frm.set_value('net_weight_kg', net);
		frm.set_value('gross_weight_kg', parseFloat((net + (frm.doc.empty_weight_g || 0) / 1000).toFixed(3)));
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


// ── Add Item Dialog ────────────────────────────────────────────────────────

function reset_and_focus(d) {
	// Fully reset the Link field so it shows the search dropdown again next time
	d.set_value('item_code', '');
	d.set_value('item_name', '');
	d.set_value('uom', '');
	d.set_value('item_weight_kg', 0);
	d.set_value('qty', 1);
	setTimeout(() => {
		let $input = d.fields_dict.item_code && d.fields_dict.item_code.$input;
		if ($input) {
			$input.val('');
			$input.trigger('input');   // resets the autocomplete state
			$input.focus();
		}
	}, 80);
}

function show_add_item_dialog(frm) {
	let d = new frappe.ui.Dialog({
		title: __('Add Item to Carton'),
		fields: [
			{
				fieldname: 'item_code',
				fieldtype: 'Link',
				label: __('Item Code'),
				options: 'Item',
				reqd: 1,
				onchange: function() {
					let item_code = d.get_value('item_code');
					if (!item_code) return;
					frappe.db.get_doc('Item', item_code).then(item => {
						d.set_value('item_name', item.item_name || '');
						d.set_value('uom', item.stock_uom || '');
						d.set_value('item_weight_kg', item.weight_per_unit || 0);
						// Focus qty field after item is selected
						d.get_field('qty').df.reqd = 1;
						d.fields_dict.qty.$input && d.fields_dict.qty.$input.focus();
					});
				}
			},
			{
				fieldname: 'item_name',
				fieldtype: 'Data',
				label: __('Item Name'),
				read_only: 1
			},
			{
				fieldtype: 'Column Break'
			},
			{
				fieldname: 'qty',
				fieldtype: 'Float',
				label: __('Qty'),
				reqd: 1,
				default: 1
			},
			{
				fieldname: 'uom',
				fieldtype: 'Data',
				label: __('UOM'),
				read_only: 1
			},
			{
				fieldname: 'item_weight_kg',
				fieldtype: 'Float',
				label: __('Weight per Unit (kg)'),
				read_only: 1,
				hidden: 1
			}
		],
		primary_action_label: __('Add to Carton'),
		primary_action: function(values) {
			// Validate without opening a blocking modal (so Escape doesn't close this dialog)
			if (!values.item_code) {
				frappe.show_alert({ message: __('Please select an Item Code first.'), indicator: 'orange' }, 3);
				reset_and_focus(d);
				return;
			}
			if (!(values.qty > 0)) {
				frappe.show_alert({ message: __('Qty must be greater than zero.'), indicator: 'orange' }, 3);
				d.fields_dict.qty.$input && d.fields_dict.qty.$input.focus();
				return;
			}

			// Check if item already exists in the table → increment qty instead
			let existing = (frm.doc.items || []).find(r => r.item_code === values.item_code);
			if (existing) {
				let new_qty = (existing.qty || 0) + values.qty;
				frappe.model.set_value(existing.doctype, existing.name, 'qty', new_qty);
				frm.trigger('calculate_gross_weight');
				frappe.show_alert({
					message: __(`${values.item_code} — qty updated to ${new_qty}`),
					indicator: 'blue'
				}, 3);
			} else {
				frm.add_child('items', {
					item_code: values.item_code,
					item_name: values.item_name || '',
					qty: values.qty,
					uom: values.uom || '',
					item_weight_kg: values.item_weight_kg || 0
				});
				frm.trigger('calculate_gross_weight');
				frappe.show_alert({
					message: __(`${values.item_code} added`),
					indicator: 'green'
				}, 3);
			}

			frm.refresh_field('items');

			// Reset dialog and re-focus item code field for the next item
			reset_and_focus(d);
		},
		secondary_action_label: __('Done'),
		secondary_action: function() {
			d.hide();
		}
	});

	// Prevent Escape from closing this dialog (so dismissing validation alerts doesn't exit)
	d.$wrapper.on('keydown.add-item-dialog', function(e) {
		if (e.key === 'Escape') {
			e.stopPropagation();
		}
	});

	d.show();
	// Auto-focus item code field when dialog opens
	setTimeout(() => reset_and_focus(d), 300);
}
