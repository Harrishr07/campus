frappe.query_reports["Metric Drill-down"] = {
	filters: [
		{ fieldname: "metric_value", label: __("Metric Value"), fieldtype: "Link", options: "Metric Value", reqd: 1 },
	],
};
