// M16-02 Pre-send preview: how many people this rule addresses right now.
frappe.ui.form.on("Audience Rule", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Preview Recipients"), () =>
			frappe
				.xcall("campus.campus_messaging.doctype.audience_rule.audience_rule.preview_count", {
					audience_rule: frm.doc.name,
				})
				.then((count) => frappe.msgprint(__("This rule addresses {0} recipients.", [count])))
		);
	},
});
