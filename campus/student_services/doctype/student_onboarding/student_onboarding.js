frappe.ui.form.on("Student Onboarding", {
	student(frm) {
		if (!frm.doc.student || (frm.doc.items && frm.doc.items.length)) {
			return;
		}
		frm.call({
			method: "campus.student_services.doctype.student_onboarding.student_onboarding.get_onboarding_template_details",
			args: { student: frm.doc.student },
			callback(r) {
				if (r.message && r.message.template) {
					frm.set_value("template", r.message.template);
					populate_items(frm, r.message.items);
				}
			},
		});
	},

	template(frm) {
		if (!frm.doc.template || (frm.doc.items && frm.doc.items.length)) {
			return;
		}
		frm.call({
			method: "campus.student_services.doctype.student_onboarding.student_onboarding.get_onboarding_template_details",
			args: { template: frm.doc.template },
			callback(r) {
				if (r.message && r.message.items) {
					populate_items(frm, r.message.items);
				}
			},
		});
	},
});

function populate_items(frm, items) {
	if (!items || !items.length) return;
	frm.clear_table("items");
	items.forEach((row) => {
		let child = frm.add_child("items");
		child.item_code = row.item_code;
		child.title = row.title;
		child.mandatory = row.mandatory;
		child.requires_attachment = row.requires_attachment;
		child.status = "Pending";
	});
	frm.refresh_field("items");
}
