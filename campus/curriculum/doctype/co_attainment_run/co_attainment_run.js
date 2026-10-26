// M03-03 CO Attainment Run: Compute queues the run on the bulk runner; the list computes every offering of a term.
frappe.ui.form.on("CO Attainment Run", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.add_custom_button(__("Compute"), () =>
			frappe
				.call({
					method: "campus.curriculum.attainment.queue_co_run",
					args: { name: frm.doc.name },
				})
				.then(() => {
					frappe.show_alert(__("Computing in the background"));
					frm.reload_doc();
				})
		);
	},
});
