frappe.ui.form.on("Seat Matrix", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Recount"), () => {
				frappe.call({
					method: "campus.admissions.seat_matrix.recount_seat_matrix",
					args: { name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
