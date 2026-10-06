frappe.ui.form.on("Accreditation Cycle", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Compute"), () =>
			frappe.xcall("campus.iqac.api.compute_cycle", { cycle: frm.doc.name }).then((values) => {
				frappe.show_alert({ message: __("{0} metric(s) computed", [values.length]), indicator: "green" });
				frappe.set_route("List", "Metric Value", { cycle: frm.doc.name });
			})
		);
	},
});
