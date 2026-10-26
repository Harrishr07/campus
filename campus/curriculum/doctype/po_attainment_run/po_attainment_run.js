// M03-03 PO Attainment Run: Compute queues the run on the bulk runner.
frappe.ui.form.on("PO Attainment Run", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.add_custom_button(__("Compute"), () =>
			frappe
				.call({
					method: "campus.curriculum.attainment.queue_po_run",
					args: { name: frm.doc.name },
				})
				.then(() => {
					frappe.show_alert(__("Computing in the background"));
					frm.reload_doc();
				})
		);
	},
});
