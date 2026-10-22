frappe.ui.form.on("Exam Session", {
	refresh(frm) {
		if (frm.is_new()) return;
		// after publication a re-run makes new result versions (with a change log) instead of replacing them
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
		if (frm.doc.status === "Published") return;
		frm.add_custom_button(__("Publish Results"), () => {
			frappe.prompt(
				[
					{ fieldname: "passing_board_meeting", fieldtype: "Link", options: "Body Meeting", label: __("Passing Board Meeting"), reqd: 1 },
					{ fieldname: "resolution_no", fieldtype: "Data", label: __("Resolution No"), reqd: 1 },
					{ fieldname: "release_at", fieldtype: "Datetime", label: __("Release At"), reqd: 1 },
				],
				(values) =>
					frappe
						.xcall("campus.examinations.publication.publish_results", { exam_session: frm.doc.name, ...values })
						.then(() => frm.reload_doc()),
				__("Publish Results")
			);
		});
		frm.add_custom_button(__("Create Exam Registrations"), () => {
			frappe.prompt(
				{ fieldname: "program", fieldtype: "Link", options: "Program", label: __("Program (blank: all)") },
				({ program }) =>
					frappe
						.xcall("campus.examinations.api.start_registration", { exam_session: frm.doc.name, program })
						.then(() => frappe.show_alert({ message: __("Exam registration queued"), indicator: "green" })),
				__("Create Exam Registrations")
			);
		});
		frm.add_custom_button(__("Re-raise Exam Fee Invoices"), () =>
			frappe
				.xcall("campus.examinations.api.reraise_exam_fee_invoices", { exam_session: frm.doc.name })
				.then((run) => run && frappe.show_alert({ message: __("Exam fee invoices queued"), indicator: "green" }))
		);
		frm.add_custom_button(__("Generate Hall Tickets"), () =>
			frappe
				.xcall("campus.examinations.api.generate_hall_tickets", { exam_session: frm.doc.name })
				.then(() => frappe.show_alert({ message: __("Hall ticket generation queued"), indicator: "green" }))
		);
	},
});
