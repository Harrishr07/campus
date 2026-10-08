frappe.ui.form.on("External Member", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.supplier) return;
		frm.add_custom_button(__("Create Supplier"), () =>
			frm.call("create_supplier").then(() => frm.reload_doc())
		);
	},
});
