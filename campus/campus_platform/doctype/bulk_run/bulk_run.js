frappe.ui.form.on("Bulk Run", {
	refresh(frm) {
		frm.disable_save();
		frm.trigger("show_progress");
		frm.trigger("add_resume_button");
		if (!frm.doc.__islocal) {
			frappe.realtime.off("bulk_run_progress");
			frappe.realtime.on("bulk_run_progress", (data) => {
				if (data.name !== frm.doc.name) return;
				Object.assign(frm.doc, {
					done: data.done,
					failed: data.failed,
					status: data.status,
				});
				frm.trigger("show_progress");
				if (!["Queued", "Running"].includes(data.status)) frm.reload_doc();
			});
		}
	},

	show_progress(frm) {
		frm.dashboard.hide_progress();
		const total = frm.doc.total || 0;
		if (!total) return;
		const processed = (frm.doc.done || 0) + (frm.doc.failed || 0);
		frm.dashboard.add_progress(
			__("Progress"),
			Math.round((processed / total) * 100),
			__("{0} of {1} processed, {2} failed", [processed, total, frm.doc.failed || 0])
		);
	},

	add_resume_button(frm) {
		if (!["Queued", "Running", "Failed"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Resume"), () => {
			frappe.call({
				method: "campus.campus_platform.bulk.resume_bulk",
				args: { name: frm.doc.name },
				callback: () => frm.reload_doc(),
			});
		});
	},
});
