// M05-15 Completion Check: run the checks of a programme (and batch) of a college in the background.
frappe.listview_settings["Completion Check"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Run Checks"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Run Completion Checks"),
				fields: [
					{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1 },
					{ fieldname: "program", fieldtype: "Link", options: "Program", label: __("Program"), reqd: 1 },
					{ fieldname: "batch", fieldtype: "Link", options: "Academic Year", label: __("Batch") },
				],
				primary_action_label: __("Run"),
				primary_action(values) {
					frappe
						.call({ method: "campus.examinations.completion.run_completion_checks", args: values, freeze: true })
						.then((r) => {
							dialog.hide();
							frappe.show_alert(__("Completion checks queued: {0}", [r.message]));
						});
				},
			});
			dialog.show();
		});
	},
};
