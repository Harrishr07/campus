// M04-01 Admit button: the server (campus.admissions.api.admit) checks role, eligibility, documents and seat.
const ADMIT = "campus.admissions.api.admit";

frappe.ui.form.on("Student Applicant", {
	refresh(frm) {
		const allowed = frappe.user.has_role("Admission Officer") || frappe.session.user === "Administrator";
		if (frm.is_new() || frm.doc.application_status !== "Approved" || !allowed) return;
		frm.add_custom_button(__("Admit"), () =>
			frappe.confirm(__("Admit {0}?", [frm.doc.name]), () =>
				frappe.call({ method: ADMIT, type: "POST", args: { applicant: frm.doc.name }, freeze: true }).then((r) => {
					frappe.show_alert({ message: __("Admitted as {0}", [r.message.student]), indicator: "green" });
					frm.reload_doc();
					frappe.set_route("Form", "Student", r.message.student);
				})
			)
		);
	},
});
