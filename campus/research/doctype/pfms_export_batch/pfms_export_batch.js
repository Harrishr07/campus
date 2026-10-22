// M08-07 PFMS Export Batch: upload PFMS's status file to update the rows.
frappe.ui.form.on("PFMS Export Batch", {
	refresh(frm) {
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
						const skipped = (result.skipped || []).map((line) => frappe.utils.escape_html(line)).join("<br>");
						frappe.msgprint(__("{0} rows updated.", [result.updated || 0]) + (skipped ? "<br><br>" + skipped : ""));
						frm.reload_doc();
					});
				},
			});
		});
	},
});
