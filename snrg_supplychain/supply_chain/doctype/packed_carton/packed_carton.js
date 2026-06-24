frappe.ui.form.on('Packed Carton', {

	refresh: function(frm) {
		if (frm.is_new()) {
			frappe.set_route('packing_station', 'new');
			return;
		}

		prune_blank_item_rows(frm);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Open Carton Packing'), () => {
				frappe.set_route('packing_station', frm.doc.name);
			}).addClass('btn-primary');
		}
	},

	box_type: function(frm) {
		if (frm.doc.box_type) {
			frappe.db.get_doc('Carton Type', frm.doc.box_type)
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

const WEIGHT_UOM_TO_KG = {
	kg: 1,
	kilogram: 1,
	kilograms: 1,
	g: 0.001,
	gm: 0.001,
	gram: 0.001,
	grams: 0.001,
	mg: 0.000001,
	milligram: 0.000001,
	milligrams: 0.000001
};

function convertWeightToKg(weight, weightUom) {
	const numericWeight = flt(weight);
	if (!numericWeight) return 0;

	const key = (weightUom || 'kg').trim().toLowerCase();
	const factor = WEIGHT_UOM_TO_KG[key];
	if (factor === undefined) {
		frappe.throw(
			__('Unsupported Weight UOM: {0}. Please use Kg, Gram, or Milligram on the Item master.', [weightUom || 'blank'])
		);
	}

	return numericWeight * factor;
}

function is_blank_item_row(row) {
	return row && !row.item_code && !row.item_name && !row.qty && !row.item_weight_kg;
}

function prune_blank_item_rows(frm) {
	if (!frm.doc.items || !frm.doc.items.length) return;

	const blank_rows = frm.doc.items.filter(is_blank_item_row);
	if (!blank_rows.length) return;

	blank_rows.forEach(row => {
		frappe.model.clear_doc(row.doctype, row.name);
	});

	frm.refresh_field('items');
}

// When item_code is selected in child table → fetch item name, UOM, weight
frappe.ui.form.on('Packed Carton Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code) {
			frappe.db.get_doc('Item', row.item_code).then(item => {
				frappe.model.set_value(cdt, cdn, 'item_name', item.item_name);
				frappe.model.set_value(cdt, cdn, 'uom', item.stock_uom);
				frappe.model.set_value(cdt, cdn, 'item_weight_kg', convertWeightToKg(item.weight_per_unit, item.weight_uom));
				frm.trigger('calculate_gross_weight');
			});
		}
	},
	qty: function(frm) { frm.trigger('calculate_gross_weight'); }
});
