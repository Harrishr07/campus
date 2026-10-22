// M03-01 Effective curricula are read-only; changes go through a new version.
frappe.ui.form.on("Curriculum", {
	refresh(frm) {
		if (["Effective", "Superseded"].includes(frm.doc.status)) {
			frm.disable_form();
		}
		if (!frm.is_new() && ["Approved", "Effective"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Create New Version"), () =>
				frappe
					.xcall("campus.curriculum.doctype.curriculum.curriculum.create_new_version", {
						curriculum: frm.doc.name,
					})
					.then((name) => frappe.set_route("Form", "Curriculum", name))
			);
		}
	},
});
