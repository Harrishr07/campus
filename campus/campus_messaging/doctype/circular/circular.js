// M16-03 Circular: audience preview before submitting.
frappe.ui.form.on("Circular", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.audience_rule) {
			frm.add_custom_button(__("Preview Recipients"), () =>
				frappe
					.xcall("campus.campus_messaging.doctype.audience_rule.audience_rule.preview_count", {
						audience_rule: frm.doc.audience_rule,
					})
					.then((count) => frappe.msgprint(__("This circular will reach {0} recipients.", [count])))
			);
		}
	},
});
