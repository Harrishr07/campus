frappe.ui.form.on("Attendance Eligibility Run", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.locked) return;
		frm.add_custom_button(__("Run"), () =>
			frm.call("start_run").then(() => {
				frappe.show_alert({ message: __("Run queued"), indicator: "green" });
				frm.reload_doc();
			})
		);
		frm.add_custom_button(__("Lock"), () =>
			frappe.confirm(__("Lock this snapshot? It cannot be run again."), () =>
				frm.call("lock_run").then(() => frm.reload_doc())
			)
		);
	},
});
