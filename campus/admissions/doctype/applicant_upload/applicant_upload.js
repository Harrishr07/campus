frappe.ui.form.on("Applicant Upload", {
	refresh(frm) {
		const call = (method) =>
			frappe.call({ method: `campus.admissions.applicant_upload.${method}`, args: { name: frm.doc.name }, freeze: true, callback: () => frm.reload_doc() });
		frm.add_custom_button(__("Download Template"), () => {
			window.open("/api/method/campus.admissions.applicant_upload.download_template");
		});
		if (frm.is_new()) return;
		if (["Draft", "Validated"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Validate"), () => call("validate_upload"));
		}
		if (frm.doc.status === "Validated") {
			frm.add_custom_button(__("Import"), () => call("start_import")).addClass("btn-primary");
		}
		if (frm.doc.status !== "Draft") {
			frm.add_custom_button(__("View Rows"), () => frappe.set_route("List", "Applicant Upload Row", { applicant_upload: frm.doc.name }));
		}
	},
});
