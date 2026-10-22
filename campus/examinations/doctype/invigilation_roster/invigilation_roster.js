frappe.ui.form.on("Invigilation Roster", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate Roster"), () =>
			frappe.xcall("campus.examinations.api.generate_invigilation", { roster: frm.doc.name }).then((duties) => {
				frappe.show_alert({ message: __("{0} invigilation duties", [duties]), indicator: "green" });
				frm.reload_doc();
			})
		);
	},
});
