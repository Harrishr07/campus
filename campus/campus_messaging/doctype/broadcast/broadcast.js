// M16-02 Broadcast: recipient preview before sending, and a counts refresh while it is going out.
const BROADCAST = "campus.campus_messaging.doctype.broadcast.broadcast.";
const PREVIEW = "campus.campus_messaging.doctype.audience_rule.audience_rule.preview_count";

frappe.ui.form.on("Broadcast", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.audience_rule) {
			frm.add_custom_button(__("Preview Recipients"), () =>
				frappe
					.xcall(PREVIEW, { audience_rule: frm.doc.audience_rule })
					.then((count) => frappe.msgprint(__("This broadcast will reach {0} recipients.", [count])))
			);
		}
		if (frm.doc.docstatus === 1 && ["Sending", "Sent"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Refresh Counts"), () =>
				frappe.xcall(BROADCAST + "refresh_status", { name: frm.doc.name }).then(() => frm.reload_doc())
			);
		}
	},
});
