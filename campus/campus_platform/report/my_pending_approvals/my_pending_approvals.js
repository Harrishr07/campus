frappe.query_reports["My Pending Approvals"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "due_at" && data && data.overdue) {
			value = `<span class="text-danger">${value}</span>`;
		}
		return value;
	},
};
