frappe.ui.form.on("Timetable Generation Run", {
	refresh(frm) {
		if (!["Queued", "Running"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Cancel Run"), () => {
			frappe.call({
				method: "campus.faculty.timetable.generation.cancel_run",
				args: { run: frm.doc.name },
				callback: () => frm.reload_doc(),
			});
		});
	},
});
