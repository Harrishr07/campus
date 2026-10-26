// M08-10 Consultancy Project: raise a GST invoice for an amount of the agreement and share a paid invoice's revenue.
frappe.ui.form.on("Consultancy Project", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Agreed", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Sales Invoice"),
				() => {
					frappe.prompt(
						[
							{
								fieldname: "amount",
								fieldtype: "Currency",
								label: __("Amount (before GST)"),
								reqd: 1,
							},
							{
								fieldname: "description",
								fieldtype: "Small Text",
								label: __("Description"),
							},
						],
						(values) =>
							frappe
								.xcall("campus.research.consultancy.make_sales_invoice", {
									project: frm.doc.name,
									...values,
								})
								.then((name) => frappe.set_route("Form", "Sales Invoice", name)),
						__("Invoice the client"),
						__("Create Draft")
					);
				},
				__("Create")
			);
		}
		frm.add_custom_button(
			__("Revenue Share"),
			() => {
				frappe.new_doc("Consultancy Revenue Share", { consultancy_project: frm.doc.name });
			},
			__("Create")
		);
		frm.add_custom_button(
			__("Invoices"),
			() => {
				frappe.set_route("List", "Sales Invoice", {
					oc_consultancy_project: frm.doc.name,
				});
			},
			__("View")
		);
	},
});
