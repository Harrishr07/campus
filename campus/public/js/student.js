// M05-01 Student form: onboarding completion link and ID card issue (photo + verifiable QR).
// M04-09 Confirm Joining: an admitted student's enrollment, ID, fee invoice and attendance start follow joining.
const CONFIRM_JOINING = "campus.admissions.api.confirm_joining";

function confirm_joining(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Confirm Joining"),
		fields: [
			{
				fieldname: "joining_date",
				fieldtype: "Date",
				label: __("Joining Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "override_justification",
				fieldtype: "Small Text",
				label: __("Seat Override Justification"),
				description: __(
					"Only when the seat matrix has no free seat or no row and you hold Admission Override."
				),
			},
		],
		primary_action_label: __("Confirm Joining"),
		primary_action(values) {
			frappe
				.call({
					method: CONFIRM_JOINING,
					type: "POST",
					freeze: true,
					args: { applicant: frm.doc.student_applicant, ...values },
				})
				.then((r) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Joined: register no {0}", [r.message.register_no]),
						indicator: "green",
					});
					frm.reload_doc();
				});
		},
	});
	dialog.show();
}

frappe.ui.form.on("Student", {
	refresh(frm) {
		if (frm.is_new()) return;
		const officer =
			frappe.user.has_role("Admission Officer") || frappe.session.user === "Administrator";
		if (
			officer &&
			frm.doc.student_applicant &&
			["Admitted", "Joined"].includes(frm.doc.oc_academic_status)
		) {
			frm.add_custom_button(__("Confirm Joining"), () => confirm_joining(frm));
		}
		frm.add_custom_button(
			__("Student Onboarding"),
			() => {
				frappe.set_route("List", "Student Onboarding", { student: frm.doc.name });
			},
			__("View")
		);
		frm.add_custom_button(
			__("Student 360"),
			() => frappe.set_route("student-360", frm.doc.name),
			__("View")
		);
		frm.add_custom_button(
			__("Correct Record"),
			() => {
				frappe.new_doc("Student Record Correction", { student: frm.doc.name });
			},
			__("Create")
		);
		frm.add_custom_button(
			__("Issue ID Card"),
			() => {
				frappe.call({
					method: "campus.student_services.api.issue_id_card",
					args: { student: frm.doc.name },
					freeze: true,
					callback: () => {
						frappe.set_route("print", "Student", frm.doc.name);
					},
				});
			},
			__("Create")
		);
	},
});
