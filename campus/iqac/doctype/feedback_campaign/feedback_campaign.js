frappe.ui.form.on("Feedback Campaign", {
	setup(frm) {
		frm.set_query("course_offering", () => ({
			filters: { group_based_on: "Course", oc_company: frm.doc.company },
		}));
		frm.set_query("audience_rule", () => ({ filters: { company: frm.doc.company } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			frm.doc.invitations_sent ? __("Send Invitations Again") : __("Send Invitations"),
			() =>
				frappe
					.xcall("campus.iqac.api.send_feedback_invitations", { campaign: frm.doc.name })
					.then(() => {
						frappe.show_alert({
							message: __("Invitations queued; see Bulk Run"),
							indicator: "blue",
						});
						frm.reload_doc();
					})
		);
		frm.add_custom_button(__("Analysis"), () =>
			frappe.set_route("query-report", "Feedback Analysis", {
				company: frm.doc.company,
				campaign: frm.doc.name,
			})
		);
	},
});
