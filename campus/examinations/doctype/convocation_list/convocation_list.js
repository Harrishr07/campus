// M06-07 Convocation List: fill the eligible graduates, mark them graduated (M05-09) and download the export.
frappe.ui.form.on("Convocation List", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Get Graduates"), () =>
			frappe
				.call({
					method: "campus.examinations.api.fill_convocation_list",
					args: { convocation_list: frm.doc.name },
					freeze: true,
				})
				.then((r) => {
					frappe.show_alert(__("{0} graduates listed", [r.message]));
					frm.reload_doc();
				})
		);
		if (frm.doc.convocation_date && frm.doc.convocation_date <= frappe.datetime.get_today()) {
			frm.add_custom_button(__("Mark Graduated"), () =>
				frappe
					.call({
						method: "campus.examinations.api.graduate_convocation_list",
						args: { convocation_list: frm.doc.name },
						freeze: true,
					})
					.then((r) => {
						frappe.show_alert(__("{0} graduates recorded", [r.message.graduated]));
						if (r.message.refused.length) {
							frappe.msgprint({
								title: __("Not recorded"),
								message: r.message.refused.map((row) => `${row.student}: ${row.reason}`).join("<br>"),
							});
						}
					})
			);
		}
		frm.add_custom_button(__("Download"), () =>
			window.open(
				"/api/method/campus.examinations.api.download_convocation_list?convocation_list=" +
					encodeURIComponent(frm.doc.name)
			)
		);
	},
});
