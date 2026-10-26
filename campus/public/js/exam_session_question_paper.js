// M06-03 Withdraw a course's question paper from its Exam Session, without opening the paper (COE / System Manager).
frappe.ui.form.on("Exam Session", {
	refresh(frm) {
		if (
			frm.is_new() ||
			!(frappe.user.has_role("COE") || frappe.user.has_role("System Manager"))
		)
			return;
		frm.add_custom_button(
			__("Withdraw Question Paper"),
			() =>
				frappe.prompt(
					[
						{
							fieldname: "course",
							label: __("Course"),
							fieldtype: "Select",
							reqd: 1,
							options: [
								...new Set((frm.doc.schedule || []).map((row) => row.course)),
							].join("\n"),
						},
						{
							fieldname: "reason",
							label: __("Reason"),
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					({ course, reason }) =>
						frappe
							.call({
								method: "campus.examinations.question_papers.withdraw_course_paper",
								args: { exam_session: frm.doc.name, course, reason },
							})
							.then((r) =>
								frappe.show_alert({
									message: __("Withdrawn: {0}", [
										(r.message || []).join(", ") || __("none"),
									]),
									indicator: "orange",
								})
							),
					__("Withdraw the course's question paper for good?"),
					__("Withdraw")
				),
			__("Question Paper")
		);
	},
});
