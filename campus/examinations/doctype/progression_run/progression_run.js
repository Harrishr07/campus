// M05-03 Progression Run: submitting queues the run; Re-run queues it again (idempotent).
frappe.ui.form.on("Progression Run", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Re-run"), () =>
			frappe
				.call({
					method: "campus.examinations.api.rerun_progression",
					args: { progression_run: frm.doc.name },
				})
				.then(() => {
					frappe.show_alert(__("Progression Run queued"));
					frm.reload_doc();
				})
		);
	},
});
