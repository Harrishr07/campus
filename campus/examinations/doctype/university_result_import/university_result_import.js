frappe.ui.form.on("University Result Import", {
	setup(frm) {
		frm.set_query("exam_session", () => ({ filters: { examination_mode: "Affiliated" } }));
		frm.set_query("import_format", () => ({ filters: { direction: "Import" } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method) =>
			frappe.call({
				method: `campus.examinations.university_import.${method}`,
				args: { name: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		if (["Draft", "Validated"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Validate"), () => call("validate_import"));
		}
		if (frm.doc.status === "Validated") {
			frm.add_custom_button(__("Import"), () => call("start_import")).addClass("btn-primary");
		}
		if (frm.doc.status !== "Draft") {
			frm.add_custom_button(__("View Rows"), () =>
				frappe.set_route("List", "University Result Import Row", { university_result_import: frm.doc.name })
			);
		}
	},
});
