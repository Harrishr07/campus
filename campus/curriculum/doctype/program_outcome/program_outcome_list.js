// M03-02 Seed the NBA PO1-PO12 of a programme under a regulation.
frappe.listview_settings["Program Outcome"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Seed NBA POs"), () => {
			frappe.prompt(
				[
					{
						fieldname: "program",
						fieldtype: "Link",
						options: "Program",
						label: __("Program"),
						reqd: 1,
					},
					{
						fieldname: "regulation",
						fieldtype: "Link",
						options: "Regulation",
						label: __("Regulation"),
						reqd: 1,
					},
				],
				(values) =>
					frappe
						.call({
							method: "campus.curriculum.api.seed_program_outcomes",
							args: values,
						})
						.then((r) => {
							frappe.show_alert(
								__("{0} outcomes added", [(r.message || []).length])
							);
							listview.refresh();
						}),
				__("Seed NBA Programme Outcomes")
			);
		});
	},
};
