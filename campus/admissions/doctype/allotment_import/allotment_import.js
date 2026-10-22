frappe.ui.form.on("Allotment Import", {
	refresh(frm) {
		if (frm.doc.status === "Draft" && !frm.is_new()) {
			frm.add_custom_button(__("Start Import"), () => {
				frappe.call({
					method: "campus.admissions.allotment_import.start_import",
					args: { name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
