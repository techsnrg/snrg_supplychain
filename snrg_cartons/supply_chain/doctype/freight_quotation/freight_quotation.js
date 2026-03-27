// Color coding for freight options child table rows
const PIN_STATUS_COLORS = {
	'Serviceable': 'green',
	'ODA': 'orange',
	'NSZ': 'red',
	'Not Listed': 'red'
};

frappe.ui.form.on('Freight Quotation', {
	refresh: function(frm) {
		frm.trigger('setup_address_filter');
		frm.trigger('add_action_buttons');
		frm.trigger('color_rows');

		// Status badge
		if (frm.doc.status === 'Finalized') {
			frm.dashboard.set_headline_alert(
				`<span class="indicator green">Finalized — ${frm.doc.selected_transporter || ''}</span>`
			);
		}

		// Dispatch Log quick link
		if (frm.doc.dispatch_log) {
			frm.add_custom_button(__('View Dispatch Log'), function() {
				frappe.set_route('Form', 'Dispatch Log', frm.doc.dispatch_log);
			}, __('Links'));
		}
	},

	setup_address_filter: function(frm) {
		frm.set_query('delivery_address', function() {
			if (!frm.doc.customer) return {};
			return {
				query: 'frappe.contacts.doctype.address.address.address_query',
				filters: { link_doctype: 'Customer', link_name: frm.doc.customer }
			};
		});
	},

	add_action_buttons: function(frm) {
		// Only show buttons in Draft status, unsaved or saved doc
		if (frm.doc.status === 'Finalized') return;

		// Calculate Freight
		frm.add_custom_button(__('Calculate Freight'), function() {
			if (!frm.doc.delivery_address) {
				frappe.msgprint({
					title: __('Missing Address'),
					message: __('Please select a Delivery Address first.'),
					indicator: 'orange'
				});
				return;
			}

			// Save first if dirty
			let do_calculate = function() {
				frappe.call({
					method: 'snrg_cartons.supply_chain.doctype.freight_quotation.freight_quotation.calculate_freight',
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __('Calculating freight for all transporters...'),
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
						}
					}
				});
			};

			if (frm.is_dirty()) {
				frm.save().then(() => do_calculate());
			} else {
				do_calculate();
			}
		}, __('Actions'));

		// Finalize Selection (only if freight options exist and one is selected)
		let has_selection = (frm.doc.freight_options || []).some(r => r.is_selected);
		if (has_selection && frm.doc.freight_options.length > 0) {
			frm.add_custom_button(__('Finalize Selection'), function() {
				frappe.confirm(
					__('This will lock the selected transporter and update the Dispatch Log. Continue?'),
					function() {
						frappe.call({
							method: 'snrg_cartons.supply_chain.doctype.freight_quotation.freight_quotation.finalize_selection',
							args: { name: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.exc && r.message) {
									frappe.show_alert({
										message: __(`Transporter <strong>${r.message.transporter}</strong> selected. Freight: ₹${r.message.amount}`),
										indicator: 'green'
									}, 7);
									frm.reload_doc();
								}
							}
						});
					}
				);
			}, __('Actions'));
		}
	},

	delivery_address: function(frm) {
		if (!frm.doc.delivery_address) {
			frm.set_value('pin_code', '');
			frm.set_value('matched_city', '');
			frm.set_value('matched_freight_zone', '');
			return;
		}
		frappe.db.get_doc('Address', frm.doc.delivery_address).then(addr => {
			frm.set_value('pin_code', addr.pincode || '');
			frm.set_value('matched_city', addr.city || '');
			// Zone will be resolved server-side on Calculate Freight
		});
	},

	color_rows: function(frm) {
		// Apply CSS color-coding to freight_options rows
		frm.fields_dict['freight_options'].grid.wrapper.find('.grid-row').each(function() {
			let row_name = $(this).attr('data-name');
			if (!row_name) return;
			let row = frm.doc.freight_options.find(r => r.name === row_name);
			if (!row) return;
			let color = PIN_STATUS_COLORS[row.pin_status];
			$(this).find('.row-index').css('background-color',
				color === 'green' ? '#d4edda' :
				color === 'orange' ? '#fff3cd' :
				color === 'red' ? '#f8d7da' : ''
			);
		});
	}
});

// Child table events
frappe.ui.form.on('Freight Quotation Option', {
	is_selected: function(frm, cdt, cdn) {
		// Deselect all other rows when one is selected
		let row = locals[cdt][cdn];
		if (row.is_selected) {
			(frm.doc.freight_options || []).forEach(r => {
				if (r.name !== cdn && r.is_selected) {
					frappe.model.set_value('Freight Quotation Option', r.name, 'is_selected', 0);
				}
			});
			frm.refresh_field('freight_options');
			frm.trigger('add_action_buttons');
		}
	}
});
