// M07-04 Self-appraisal: compute the API score for an Appraisal Cycle and open the resulting HRMS Appraisal.
frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.oc_staff_type !== "Teaching") return;
		frm.add_custom_button(
			__("Self-Appraisal"),
			() =>
				frappe.prompt(
					[
						{
							fieldname: "appraisal_cycle",
							fieldtype: "Link",
							options: "Appraisal Cycle",
							label: __("Appraisal Cycle"),
							reqd: 1,
						},
					],
					(values) =>
						frappe
							.xcall("campus.faculty.api.create_self_appraisal", {
								employee: frm.doc.name,
								appraisal_cycle: values.appraisal_cycle,
							})
							.then((name) => frappe.set_route("Form", "Appraisal", name)),
					__("Create or Update Self-Appraisal")
				),
			__("Faculty")
		);
	},
});
