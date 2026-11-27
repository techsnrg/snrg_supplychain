frappe.query_reports['Overdue Supplier Deliveries'] = {
    filters: [
        {fieldname: 'company', label: __('Company'), fieldtype: 'Link', options: 'Company', reqd: 1, default: frappe.defaults.get_user_default('Company')},
        {fieldname: 'supplier', label: __('Supplier'), fieldtype: 'Link', options: 'Supplier'},
        {fieldname: 'item_code', label: __('Item'), fieldtype: 'Link', options: 'Item'},
        {fieldname: 'owner', label: __('Created By'), fieldtype: 'Link', options: 'User'},
        {fieldname: 'minimum_days', label: __('Minimum Days Overdue'), fieldtype: 'Int', default: 1}
    ]
};
