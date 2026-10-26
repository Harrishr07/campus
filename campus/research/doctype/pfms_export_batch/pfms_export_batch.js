// M08-07 PFMS Export Batch: upload PFMS's status file to update the rows; release a line held for review.
frappe.ui.form.on("PFMS Export Batch", {
	refresh(frm) {
		add_release_button(frm);
		if (frm.doc.docstatus !== 1 || !frm.has_perm("submit")) return;
		frm.add_custom_button(__("Import Status"), () => {
			new frappe.ui.FileUploader({
				doctype: frm.doctype,
				docname: frm.docname,
				make_attachments_public: false,
				restrictions: { allowed_file_types: [".csv"] },
				on_success(file) {
					frm.call("import_status", { file_url: file.file_url }).then((r) => {
						const result = r.message || {};
						const skipped = (result.skipped || [])
							.map((line) => frappe.utils.escape_html(line))
							.join("<br>");
						frappe.msgprint(
							__("{0} rows updated.", [result.updated || 0]) +
								(skipped ? "<br><br>" + skipped : "")
						);
						frm.reload_doc();
					});
				},
			});
		});
	},
});

// An Accounts Manager releases an excluded line held for review, with a reason; the server checks it again.
function add_release_button(frm) {
	if (
		frm.is_new() ||
		!(frm.doc.exclusions || []).length ||
		!frappe.user.has_role("Accounts Manager")
	)
		return;
	frm.add_custom_button(__("Release After Review"), () => {
		const options = frm.doc.exclusions.map((row) => ({
			value: row.name,
			label: `${row.voucher_no} ${row.reference_name || ""} (${format_currency(
				row.amount,
				frm.doc.currency
			)})`,
		}));
		frappe.prompt(
			[
				{
					fieldname: "exclusion",
					fieldtype: "Select",
					label: __("Excluded Line"),
					options,
					reqd: 1,
				},
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason (what was checked)"),
					reqd: 1,
				},
			],
			(values) => {
				frm.call("release_after_review", values).then((r) => {
					frappe.show_alert({
						message: __("Released: {0}", [r.message]),
						indicator: "green",
					});
					frm.reload_doc();
				});
			},
			__("Release After Review"),
			__("Release")
		);
	});
}
