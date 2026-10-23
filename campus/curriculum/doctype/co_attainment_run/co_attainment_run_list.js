frappe.listview_settings["CO Attainment Run"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Compute for a Term"), () =>
			frappe.prompt(
				[
					{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("College"), reqd: 1 },
					{ fieldname: "academic_term", fieldtype: "Link", options: "Academic Term", label: __("Academic Term"), reqd: 1 },
				],
				(values) =>
					frappe
						.call({ method: "campus.curriculum.attainment.start_term_runs", args: values })
						.then(() => {
							frappe.show_alert(__("Computing in the background"));
							listview.refresh();
						}),
				__("Compute CO Attainment for a Term")
			)
		);
	},
};
