// M12-02 Issue Grade Sheet button: the server (campus.examinations.api.issue_grade_sheet) checks role and publication.
const ISSUE_GRADE_SHEET = "campus.examinations.api.issue_grade_sheet";

// Mirrors the server rule: a Published session whose publish_at has passed.
function session_is_published(session) {
	return (
		session &&
		session.status === "Published" &&
		session.publish_at &&
		frappe.datetime.str_to_obj(session.publish_at) <= new Date()
	);
}

frappe.ui.form.on("Student Result", {
	refresh(frm) {
		const allowed = frappe.user.has_role("COE") || frappe.user.has_role("System Manager");
		if (frm.is_new() || !allowed) return;
		frappe.db
			.get_value("Exam Session", frm.doc.exam_session, ["status", "publish_at"])
			.then(({ message }) => {
				if (!session_is_published(message)) return;
				frm.add_custom_button(__("Issue Grade Sheet"), () =>
					frappe
						.call({
							method: ISSUE_GRADE_SHEET,
							type: "POST",
							args: { student_result: frm.doc.name },
							freeze: true,
						})
						.then((r) => {
							frappe.show_alert({
								message: __("Grade Sheet {0} issued", [r.message]),
								indicator: "green",
							});
							window.open(`/verify/${encodeURIComponent(r.message)}`);
						})
				);
			});
	},
});
