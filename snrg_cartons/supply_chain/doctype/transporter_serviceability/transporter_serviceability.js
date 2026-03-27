frappe.ui.form.on('Transporter Serviceability', {
	onload: function(frm) {
		// Filter transporter link to only show suppliers marked as transporter
		frm.set_query('transporter', function() {
			return { filters: { is_transporter: 1 } };
		});
	},

	refresh: function(frm) {
		// Status badge
		if (frm.doc.docstatus === 1) {
			if (frm.doc.status === 'Active') {
				frm.dashboard.set_headline_alert(
					'<span class="indicator green">Active</span>'
				);
			} else {
				frm.dashboard.set_headline_alert(
					'<span class="indicator red">Expired</span>'
				);
			}
		}

		// Upload from CSV button (only on saved/submitted docs)
		if (frm.doc.name && !frm.doc.__islocal) {
			frm.add_custom_button(__('Download CSV Template'), function() {
				let rows = [
					['PIN CODE', 'ZONE', 'STATE', 'ODA/SERVICEABILITY', 'ODA CATEGORY'],
					['110001', 'Delhi Metro', 'Delhi', 'SERVICEABLE', 'S'],
					['110002', 'Delhi Metro', 'Delhi', 'ODA', 'A'],
					['110003', 'Delhi Metro', 'Delhi', 'NSZ', ''],
					['400001', 'Mumbai Metro', 'Maharashtra', 'SERVICEABLE', 'S'],
					['500001', 'Hyderabad Metro', 'Telangana', 'ODA', 'B'],
				];
				let csv_content = rows.map(r => r.map(c => `"${c}"`).join(',')).join('\r\n');
				let blob = new Blob([csv_content], { type: 'text/csv;charset=utf-8;' });
				let url = URL.createObjectURL(blob);
				let a = document.createElement('a');
				a.href = url;
				a.download = 'pin_code_upload_template.csv';
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}, __('Tools'));

			frm.add_custom_button(__('Upload from CSV'), function() {
				let d = new frappe.ui.Dialog({
					title: __('Upload Pin Code CSV'),
					fields: [
						{
							fieldtype: 'HTML',
							options: `<div class="alert alert-info small">
								<strong>Expected columns (with header row):</strong><br>
								<code>PIN CODE, ZONE, STATE, ODA/SERVICEABILITY, ODA CATEGORY</code><br><br>
								<strong>Serviceability values:</strong> SERVICEABLE, ODA, NSZ<br>
								<strong>ODA Category values:</strong> S, A, B, C, D, E<br><br>
								<em>⚠ This will replace all existing pin code rows.</em>
							</div>`
						},
						{
							fieldtype: 'Attach',
							fieldname: 'csv_file',
							label: 'CSV / Excel File',
							reqd: 1
						}
					],
					primary_action_label: __('Process Upload'),
					primary_action(values) {
						if (!values.csv_file) {
							frappe.msgprint(__('Please attach a CSV file.'));
							return;
						}
						frappe.call({
							method: 'snrg_cartons.supply_chain.doctype.transporter_serviceability.transporter_serviceability.process_csv_upload',
							args: {
								doc_name: frm.doc.name,
								file_url: values.csv_file
							},
							freeze: true,
							freeze_message: __('Processing CSV...'),
							callback(r) {
								d.hide();
								if (r.message) {
									let { loaded, errors } = r.message;
									let msg = `<strong>${loaded} pin codes loaded successfully.</strong>`;
									if (errors && errors.length) {
										msg += `<br><br><strong>Warnings / Errors (first ${errors.length}):</strong><ul>`;
										errors.forEach(e => { msg += `<li>${e}</li>`; });
										msg += '</ul>';
									}
									frappe.msgprint({
										title: __('Upload Complete'),
										message: msg,
										indicator: errors && errors.length ? 'orange' : 'green'
									});
									frm.reload_doc();
								}
							}
						});
					}
				});
				d.show();
			}, __('Tools'));
		}
	}
});
