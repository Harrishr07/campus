// M08-10 Consultancy Revenue Share: only a submitted, fully paid invoice of the project can be shared.
frappe.ui.form.on("Consultancy Revenue Share", {
	setup(frm) {
		frm.set_query("sales_invoice", () => ({
			filters: {
				oc_consultancy_project: frm.doc.consultancy_project,
				docstatus: 1,
				is_return: 0,
				outstanding_amount: ["<=", 0],
			},
		}));
	},
	consultancy_project(frm) {
		frm.set_value("sales_invoice", null);
	},
});
