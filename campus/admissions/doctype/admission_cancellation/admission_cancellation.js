frappe.ui.form.on("Admission Cancellation", {
	program_enrollment(frm) {
		if (frm.doc.program_enrollment) {
			frappe.db.get_value("Program Enrollment", frm.doc.program_enrollment, "student", (r) => {
				frm.set_value("student", r.student);
			});
		}
	},
});
