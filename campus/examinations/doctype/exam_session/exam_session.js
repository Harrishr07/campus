frappe.ui.form.on("Exam Session", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Published") return;
		frm.add_custom_button(__("Run Results"), () => {
			frappe.prompt(
				{ fieldname: "program", fieldtype: "Link", options: "Program", label: __("Program"), reqd: 1 },
				({ program }) =>
					frappe.xcall("campus.examinations.api.run_results", { exam_session: frm.doc.name, program }).then(
						() => frappe.show_alert({ message: __("Result Run queued"), indicator: "green" })
					),
				__("Run Results")
			);
		});
	},
});
