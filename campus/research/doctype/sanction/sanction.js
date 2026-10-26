frappe.ui.form.on("Sanction", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Receive Instalment"), () =>
			frappe.new_doc("Grant Receipt", { sanction: frm.doc.name })
		);
		frm.add_custom_button(__("Extend"), () =>
			frappe.prompt(
				[
					{
						fieldname: "revised_end_date",
						fieldtype: "Date",
						label: __("Revised End Date"),
						reqd: 1,
					},
					{
						fieldname: "order_no",
						fieldtype: "Data",
						label: __("Extension Order No"),
						reqd: 1,
					},
					{
						fieldname: "order_date",
						fieldtype: "Date",
						label: __("Order Date"),
						reqd: 1,
					},
				],
				(values) => frm.call("extend_sanction", values).then(() => frm.reload_doc()),
				__("Extend Sanction")
			)
		);
	},
});
