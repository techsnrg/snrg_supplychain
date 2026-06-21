frappe.ui.form.on('Transporter Rate Card', {
	onload: function(frm) {
		// Filter transporter link to only show suppliers marked as transporter
		frm.set_query('transporter', function() {
			return { filters: { is_transporter: 1 } };
		});
	},

	refresh: function(frm) {
		// Show validity status badge
		if (frm.doc.docstatus === 1) {
			if (frm.doc.is_active) {
				frm.dashboard.set_headline_alert(
					'<span class="indicator green">Active Contract</span>'
				);
			} else if (frm.doc.valid_to && frappe.datetime.str_to_obj(frm.doc.valid_to) < new Date()) {
				frm.dashboard.set_headline_alert(
					'<span class="indicator red">Expired Contract</span>'
				);
			} else {
				frm.dashboard.set_headline_alert(
					'<span class="indicator orange">Not Yet Active</span>'
				);
			}
		}
	},

	valid_from: function(frm) {
		frm.trigger('check_validity');
	},

	valid_to: function(frm) {
		frm.trigger('check_validity');
	},

	check_validity: function(frm) {
		if (frm.doc.valid_to && frm.doc.valid_from) {
			if (frappe.datetime.str_to_obj(frm.doc.valid_to) < frappe.datetime.str_to_obj(frm.doc.valid_from)) {
				frappe.msgprint({
					title: __('Invalid Dates'),
					message: __('Valid To cannot be before Valid From.'),
					indicator: 'red'
				});
			}
		}
	}
});
