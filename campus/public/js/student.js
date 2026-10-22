// M05-01 Student form: onboarding completion link and ID card issue (photo + verifiable QR).
frappe.ui.form.on("Student", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Student Onboarding"), () => {
			frappe.set_route("List", "Student Onboarding", { student: frm.doc.name });
		}, __("View"));
		frm.add_custom_button(__("Student 360"), () => frappe.set_route("student-360", frm.doc.name), __("View"));
		frm.add_custom_button(__("Correct Record"), () => {
			frappe.new_doc("Student Record Correction", { student: frm.doc.name });
		}, __("Create"));
		frm.add_custom_button(__("Issue ID Card"), () => {
			frappe.call({
				method: "campus.student_services.api.issue_id_card",
				args: { student: frm.doc.name },
				freeze: true,
				callback: () => {
					frappe.set_route("print", "Student", frm.doc.name);
				},
			});
		}, __("Create"));
	},
});
