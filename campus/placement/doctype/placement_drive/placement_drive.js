// M14-01 Choosing an eligibility template copies its criteria into the drive (editable afterwards).
frappe.ui.form.on("Placement Drive", {
	eligibility_template(frm) {
		if (!frm.doc.eligibility_template) return;
		frappe.call({
			method: "campus.placement.eligibility.template_criteria",
			args: { template: frm.doc.eligibility_template },
			callback: (r) => {
				const v = r.message || {};
				[
					"min_cgpa",
					"any_standing_arrears",
					"max_standing_arrears",
					"allow_arrear_history",
					"gender",
				].forEach((f) => frm.set_value(f, v[f]));
				frm.clear_table("programs");
				(v.programs || []).forEach((row) => frm.add_child("programs", row));
				frm.clear_table("batches");
				(v.batches || []).forEach((row) => frm.add_child("batches", row));
				frm.refresh_fields();
			},
		});
	},
});
