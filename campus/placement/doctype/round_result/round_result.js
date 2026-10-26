// M14-02 Bulk upload and template download of round results.
frappe.ui.form.on("Round Result", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Download Registered List"), () => {
			window.open(
				`/api/method/campus.placement.round_upload.download_template?round_result=${encodeURIComponent(
					frm.doc.name
				)}`
			);
		});
	},
	load_results(frm) {
		if (frm.is_dirty()) return frappe.msgprint(__("Save the Round Result first."));
		frappe.call({
			method: "campus.placement.round_upload.load_results",
			args: { round_result: frm.doc.name },
			freeze: true,
			callback: (r) => {
				frappe.show_alert({
					message: __("{0} rows loaded", [r.message]),
					indicator: "green",
				});
				frm.reload_doc();
			},
		});
	},
});
