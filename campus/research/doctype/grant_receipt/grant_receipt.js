frappe.ui.form.on("Grant Receipt", {
	setup(frm) {
		frm.set_query("sanction", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("received_in", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				account_type: ["in", ["Bank", "Cash"]],
			},
		}));
	},
});
