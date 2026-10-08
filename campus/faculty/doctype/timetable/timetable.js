frappe.ui.form.on("Timetable", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate"), () => {
			frappe.confirm(__("Generate replaces the grid, including manual edits. Continue?"), () => {
				frappe.call({
					method: "campus.faculty.timetable.generation.start_generation",
					args: { timetable: frm.doc.name },
					callback: (r) => {
						frappe.show_alert({ message: __("Generation queued: {0}", [r.message]), indicator: "green" });
						frappe.set_route("Form", "Timetable Generation Run", r.message);
					},
				});
			});
		}, __("Actions"));
		frm.add_custom_button(__("Check Clashes"), () => {
			frappe.set_route("query-report", "Timetable Clash Checker", { company: frm.doc.company, timetable: frm.doc.name });
		}, __("Actions"));
		frm.add_custom_button(__("Publish"), () => {
			frappe.confirm(__("Publishing replaces this timetable's Course Schedules from today. Continue?"), () => {
				frappe.call({
					method: "campus.faculty.timetable.publish.publish_timetable",
					args: { timetable: frm.doc.name },
					callback: () => frappe.show_alert({ message: __("Publishing queued."), indicator: "green" }),
				});
			});
		}, __("Actions"));
	},
});
