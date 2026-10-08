frappe.ui.form.on("Seating Plan", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate Seating"), () =>
			frappe
				.xcall("campus.examinations.api.generate_seating", { seating_plan: frm.doc.name })
				.then((seated) => {
					frappe.show_alert({ message: __("{0} students seated", [seated]), indicator: "green" });
					frm.reload_doc();
				})
		);
	},
});
