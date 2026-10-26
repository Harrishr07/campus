frappe.ui.form.on("Research Proposal", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status === "Approved") {
			frm.add_custom_button(__("Submit to Agency"), () =>
				frappe.prompt(
					[
						{
							fieldname: "submission_date",
							fieldtype: "Date",
							label: __("Submitted On"),
							default: frappe.datetime.get_today(),
							reqd: 1,
						},
						{
							fieldname: "agency_reference",
							fieldtype: "Data",
							label: __("Agency Reference"),
						},
					],
					(values) => frm.call("submit_to_agency", values).then(() => frm.reload_doc()),
					__("Submit to Agency")
				)
			).addClass("btn-primary");
		}
		if (frm.doc.status === "Submitted to Agency") {
			frm.add_custom_button(__("Record Outcome"), () =>
				frappe.prompt(
					[
						{
							fieldname: "outcome",
							fieldtype: "Select",
							label: __("Outcome"),
							options: "Sanctioned\nNot Sanctioned",
							reqd: 1,
						},
						{
							fieldname: "outcome_date",
							fieldtype: "Date",
							label: __("Outcome Date"),
							default: frappe.datetime.get_today(),
							reqd: 1,
						},
					],
					(values) => frm.call("record_outcome", values).then(() => frm.reload_doc()),
					__("Record Outcome")
				)
			).addClass("btn-primary");
		}
	},
});
