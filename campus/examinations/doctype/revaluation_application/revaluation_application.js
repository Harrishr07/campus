// M06-06 Revaluation Application: Justify (a teacher of the course, draft Revaluation) and Issue Photocopy (COE).
frappe.ui.form.on("Revaluation Application", {
	refresh(frm) {
		if (
			frm.doc.docstatus === 0 &&
			!frm.is_new() &&
			frm.doc.application_type === "Revaluation"
		) {
			frm.add_custom_button(__("Justify"), () => {
				frappe.prompt(
					[
						{
							fieldname: "course",
							label: __("Course"),
							fieldtype: "Select",
							reqd: 1,
							options: frm.doc.courses.map((r) => r.course),
						},
						{
							fieldname: "justification",
							label: __("Justification"),
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					(values) =>
						frappe
							.call({
								method: "campus.examinations.revaluation.justify",
								args: { application: frm.doc.name, ...values },
							})
							.then(() => frm.reload_doc()),
					__("Faculty Justification")
				);
			});
		}
		if (frm.doc.docstatus === 1 && frm.doc.fee_amount > 0 && !frm.doc.fee_invoice) {
			frm.add_custom_button(__("Raise Fee Again"), () =>
				frappe
					.call({
						method: "campus.examinations.revaluation.reraise_fee",
						args: { application: frm.doc.name },
					})
					.then(() => frm.reload_doc())
			);
		}
		if (
			frm.doc.docstatus === 1 &&
			frm.doc.application_type === "Photocopy" &&
			!frm.doc.photocopy_issued_on
		) {
			frm.add_custom_button(__("Issue Photocopy"), () =>
				frappe
					.call({
						method: "campus.examinations.revaluation.issue_photocopy",
						args: { application: frm.doc.name },
					})
					.then(() => frm.reload_doc())
			);
		}
	},
});
