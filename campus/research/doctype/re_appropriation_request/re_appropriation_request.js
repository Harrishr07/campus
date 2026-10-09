frappe.ui.form.on("Re-appropriation Request", {
	setup(frm) {
		frm.set_query("sanction", () => ({ filters: { docstatus: 1 } }));
	},
});
