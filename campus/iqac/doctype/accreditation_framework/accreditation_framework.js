frappe.ui.form.on("Accreditation Framework", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Publish"), () =>
				frappe.confirm(__("A published framework and its nodes can no longer be edited. Publish?"), () => {
					frm.set_value("status", "Published");
					frm.save();
				})
			);
		}
		if (frm.doc.status === "Published") {
			frm.add_custom_button(__("Retire"), () =>
				frappe.confirm(__("A retired framework cannot be used for new cycles and cannot be reopened. Retire?"), () => {
					frm.set_value("status", "Retired");
					frm.save();
				})
			);
		}
		frm.add_custom_button(__("Clone to New Version"), () => clone_to_new_version(frm));
	},
});

function clone_to_new_version(frm) {
	frappe.prompt(
		[
			{ fieldname: "new_name", fieldtype: "Data", label: __("New Framework Name"), reqd: 1 },
			{ fieldname: "version", fieldtype: "Data", label: __("Version"), reqd: 1 },
		],
		(values) =>
			frappe
				.xcall("campus.iqac.api.clone_framework", { framework: frm.doc.name, ...values })
				.then((name) => frappe.set_route("Form", "Accreditation Framework", name)),
		__("Clone to New Version")
	);
}
