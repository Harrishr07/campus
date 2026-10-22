frappe.ui.form.on("Utilisation Certificate", {
	refresh(frm) {
		if (frm.doc.source_changed) {
			frm.dashboard.set_headline_alert(
				__("Source changed: a ledger entry dated in or before this period moved the figures after approval."),
				"orange"
			);
		}
		if (frm.doc.docstatus === 0 && frm.doc.unreconciled_entries) {
			frm.dashboard.set_headline_alert(
				__("{0} unreconciled entries on the project: the certificate can't be approved.", [frm.doc.unreconciled_entries]),
				"red"
			);
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Recheck Source"), () =>
				frm.call("recheck_source").then(() => frm.reload_doc())
			);
		}
	},
});
