frappe.ui.form.on("AISHE Layout", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Export AISHE Dataset"), () => {
			frappe.prompt(
				[
					{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1 },
					{ fieldname: "academic_year", fieldtype: "Link", options: "Academic Year", label: __("Academic Year"), reqd: 1 },
				],
				(values) =>
					open_url_post("/api/method/campus.iqac.api.export_aishe", { ...values, layout: frm.doc.name }),
				__("Export AISHE Dataset"),
				__("Download")
			);
		});
	},
});
