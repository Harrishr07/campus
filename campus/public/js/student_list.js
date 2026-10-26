// M05-07 Student list: the mentor allocation tool for HODs and deans.
frappe.listview_settings["Student"] = frappe.listview_settings["Student"] || {};
const onload_before = frappe.listview_settings["Student"].onload;
frappe.listview_settings["Student"].onload = function (listview) {
	if (onload_before) onload_before(listview);
	listview.page.add_menu_item(__("Allocate Mentors"), () => {
		frappe.prompt(
			[
				{
					fieldname: "student_group",
					fieldtype: "Link",
					options: "Student Group",
					label: __("Student Group"),
				},
				{
					fieldname: "program",
					fieldtype: "Link",
					options: "Program",
					label: __("Program"),
					depends_on: "eval:!doc.student_group",
				},
				{
					fieldname: "batch",
					fieldtype: "Link",
					options: "Academic Year",
					label: __("Batch"),
					depends_on: "eval:!doc.student_group",
				},
				{
					fieldname: "per_mentor",
					fieldtype: "Int",
					label: __("Maximum students per mentor"),
				},
			],
			(values) => {
				frappe.call({
					method: "campus.student_services.api.allocate_mentors",
					args: values,
					freeze: true,
					callback: (r) => {
						const lines = Object.entries(r.message || {}).map(
							([m, s]) => `${m}: ${s.length}`
						);
						frappe.msgprint(
							__("Allocated to mentors (all active Mentor position holders)") +
								"<br>" +
								lines.join("<br>")
						);
						listview.refresh();
					},
				});
			},
			__("Allocate Mentors"),
			__("Allocate")
		);
	});
};
