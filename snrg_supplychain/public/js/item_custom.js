frappe.ui.form.on('Item', {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__('Product Box Sticker'), () => {
			show_product_box_sticker_dialog(frm);
		}, __('Print'));
	}
});

function show_product_box_sticker_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Print Product Box Sticker'),
		fields: [
			{
				fieldname: 'box_qty',
				fieldtype: 'Float',
				label: __('Box Qty'),
				default: 1,
				reqd: 1
			},
			{
				fieldname: 'copies',
				fieldtype: 'Int',
				label: __('Copies'),
				default: 1,
				reqd: 1
			}
		],
		primary_action_label: __('Print'),
		primary_action(values) {
			if (!(flt(values.box_qty) > 0)) {
				frappe.show_alert({ message: __('Box Qty must be greater than zero.'), indicator: 'orange' }, 3);
				return;
			}

			if (!(cint(values.copies) > 0)) {
				frappe.show_alert({ message: __('Copies must be greater than zero.'), indicator: 'orange' }, 3);
				return;
			}

			print_product_box_sticker(frm.doc.name, values.box_qty, values.copies);
			dialog.hide();
		}
	});

	dialog.show();
}

function print_product_box_sticker(item_code, box_qty, copies) {
	const print_window = window.open('', '_blank');
	if (!print_window) {
		frappe.msgprint(__('Please allow pop-ups to print the product box sticker.'));
		return;
	}

	print_window.document.write(`
		<!doctype html>
		<html>
		<head><title>${__('Product Box Sticker')}</title></head>
		<body style="font-family: Arial, sans-serif; padding: 16px;">${__('Preparing sticker...')}</body>
		</html>
	`);
	print_window.document.close();

	frappe.call({
		method: 'snrg_supplychain.supply_chain.utils.get_product_box_sticker_html',
		args: {
			item_code,
			box_qty,
			copies
		},
		freeze: true,
		freeze_message: __('Preparing sticker...'),
		callback(response) {
			if (!response.message) {
				print_window.close();
				frappe.msgprint(__('Could not prepare the product box sticker.'));
				return;
			}

			print_window.document.open();
			print_window.document.write(response.message);
			print_window.document.close();
			print_window.focus();
			print_when_sticker_assets_are_ready(print_window);
		},
		error() {
			print_window.close();
			frappe.msgprint(__('Could not prepare the product box sticker.'));
		}
	});
}

function print_when_sticker_assets_are_ready(print_window) {
	const print_document = print_window.document;
	const images = Array.from(print_document.images || []);
	const ready = images.map((image) => {
		if (image.complete) return Promise.resolve();

		return new Promise((resolve) => {
			image.onload = resolve;
			image.onerror = resolve;
		});
	});

	Promise.all(ready).then(() => {
		setTimeout(() => print_window.print(), 100);
	});
}
