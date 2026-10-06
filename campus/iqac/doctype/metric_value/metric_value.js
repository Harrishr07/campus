frappe.ui.form.on("Metric Value", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Drill-down"), () =>
			frappe.set_route("query-report", "Metric Drill-down", { metric_value: frm.doc.name })
		);
	},
});
