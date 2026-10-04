frappe.ui.form.on("Regulation", {
	refresh(frm) {
		if (frm.is_new() || !["Approved", "Effective"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Amend as New Version"), () => {
			frappe.call({
				method: "campus.campus_platform.doctype.regulation.regulation.amend_as_new_version",
				args: { regulation: frm.doc.name },
				callback: (r) => frappe.set_route("Form", "Regulation", r.message),
			});
		});
	},
});
