frappe.ui.form.on("Candidate Duplicate Review", {
	refresh(frm) {
		if (frm.doc.status !== "Open") return;
		const decide = (decision, note) =>
			frappe.call({
				method: "campus.admissions.duplicates.decide",
				args: { review: frm.doc.name, decision, note },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		frm.add_custom_button(__("Link to Existing Record"), () => {
			frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("Note") }, (v) => decide("Link", v.note), __("Link"));
		});
		frm.add_custom_button(__("Not a Duplicate"), () => {
			frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }, (v) => decide("Not Duplicate", v.note), __("Not a Duplicate"));
		});
	},
});
