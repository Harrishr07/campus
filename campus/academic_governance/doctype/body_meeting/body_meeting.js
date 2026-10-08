frappe.ui.form.on("Body Meeting", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.notice_sent_on || frm.doc.status !== "Scheduled") return;
		frm.add_custom_button(__("Send Notice"), () => send_notice(frm));
		frm.add_custom_button(__("Send Late Notice"), () =>
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				(values) => send_notice(frm, values.reason),
				__("Late Notice")
			)
		);
	},
});

function send_notice(frm, override_reason) {
	frm.call({ method: "send_notice", doc: frm.doc, args: { override_reason }, freeze: true }).then(() => frm.reload_doc());
}
