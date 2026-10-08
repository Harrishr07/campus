// M07-04 A self-appraisal Appraisal is submitted only through the HOD's Appraisal Review.
frappe.ui.form.on("Appraisal", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0 || !frm.doc.oc_api_rule) return;
		frm.add_custom_button(__("Request HOD Review"), () =>
			frappe
				.xcall("campus.faculty.api.request_appraisal_review", { appraisal: frm.doc.name })
				.then((name) => frappe.set_route("Form", "Appraisal Review", name))
		);
	},
});
