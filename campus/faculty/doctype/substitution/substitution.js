frappe.ui.form.on("Substitution", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Cancelled") return;
		if (frm.doc.status === "Proposed") {
			frm.add_custom_button(__("Suggest Substitutes"), () => {
				frappe.call({
					method: "campus.faculty.api.suggest_substitutes",
					args: { course_schedule: frm.doc.course_schedule },
					callback: (r) => {
						const free = r.message || [];
						if (!free.length) return frappe.msgprint(__("Nobody in the department is free for this period."));
						frappe.prompt(
							[{ fieldname: "employee", fieldtype: "Select", label: __("Free teacher"), reqd: 1, options: free.map((f) => f.employee) }],
							(v) => frm.set_value("substitute", v.employee),
							__("Suggest Substitutes")
						);
					},
				});
			});
		}
		if (frm.doc.status === "Confirmed" && frm.doc.substitute_user === frappe.session.user) {
			frm.add_custom_button(__("Mark Attendance"), () => mark_attendance(frm));
		}
	},
});

function mark_attendance(frm) {
	frappe.db
		.get_list("Student Group Student", { filters: { parent: frm.doc.student_group, active: 1 }, fields: ["student", "student_name"], limit: 500, parent_doctype: "Student Group" })
		.then((students) => {
			const dialog = new frappe.ui.Dialog({
				title: __("Mark Attendance"),
				fields: students.map((s) => ({ fieldname: s.student, fieldtype: "Check", label: s.student_name || s.student, default: 1 })),
				primary_action_label: __("Save"),
				primary_action(values) {
					const present = students.filter((s) => values[s.student]).map((s) => s.student);
					const absent = students.filter((s) => !values[s.student]).map((s) => s.student);
					frappe.call({
						method: "campus.faculty.api.mark_substituted_attendance",
						args: { substitution: frm.doc.name, present, absent },
						callback: () => {
							dialog.hide();
							frappe.show_alert({ message: __("Attendance marked."), indicator: "green" });
						},
					});
				},
			});
			dialog.show();
		});
}
