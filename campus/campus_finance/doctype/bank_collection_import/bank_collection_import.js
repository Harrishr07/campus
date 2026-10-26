frappe.ui.form.on("Bank Collection Import", {
	refresh(frm) {
		if (frm.doc.status === "Draft" && !frm.is_new() && frm.doc.collection_file) {
			frm.add_custom_button(__("Process File"), () => {
				frappe.call({
					method: "campus.campus_finance.bank_import.start_import",
					args: { name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			}).addClass("btn-primary");
		}
		if (!frm.is_new()) {
			frm.add_custom_button(__("Rows"), () =>
				frappe.set_route("List", "Bank Collection Row", {
					bank_collection_import: frm.doc.name,
				})
			);
		}
	},
});
