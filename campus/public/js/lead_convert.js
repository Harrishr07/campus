// M04-01 Convert to Applicant: the enquiry becomes a Student Applicant (name, contact, programme, college) linked both ways.
// The server (campus.admissions.api.convert_lead_to_applicant) checks the officer's rights and is safe to call twice.
const CONVERT = "campus.admissions.api.convert_lead_to_applicant";

frappe.ui.form.on("Lead", {
	refresh(frm) {
		const allowed = frappe.user.has_role("Admission Officer") || frappe.session.user === "Administrator";
		if (frm.is_new() || !allowed) return;
		if (frm.doc.oc_applicant) {
			frm.add_custom_button(__("Open Applicant"), () => frappe.set_route("Form", "Student Applicant", frm.doc.oc_applicant));
			return;
		}
		frm.add_custom_button(__("Convert to Applicant"), () =>
			frappe.call({ method: CONVERT, type: "POST", args: { lead: frm.doc.name }, freeze: true }).then((r) => {
				frappe.show_alert({ message: __("Converted to Applicant {0}", [r.message]), indicator: "green" });
				frm.reload_doc();
				frappe.set_route("Form", "Student Applicant", r.message);
			})
		);
	},
});
