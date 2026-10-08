// M06-03 Question Paper: download (POST, watermarked, inside the window), record printed copies, withdraw.
const QP_API = "campus.examinations.question_papers";

frappe.ui.form.on("Question Paper", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 1) {
			["A", "B"].filter((s) => frm.doc[`set_${s.toLowerCase()}_file`]).forEach((paper_set) => {
				frm.add_custom_button(__("Set {0}", [paper_set]), () =>
					open_url_post(`/api/method/${QP_API}.download_paper`, { question_paper: frm.doc.name, paper_set }, true),
				__("Download"));
			});
			frm.add_custom_button(__("Record Print"), () => record_print(frm));
		}
		if (frm.doc.docstatus < 2 && frm.doc.moderation_status !== "Withdrawn") {
			frm.add_custom_button(__("Withdraw"), () =>
				frappe.confirm(__("Withdraw this paper for good? It can never be downloaded again."), () =>
					frappe.call({ method: `${QP_API}.withdraw`, args: { question_paper: frm.doc.name } }).then(() => frm.reload_doc())
				));
		}
	},
});

function record_print(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Record Printed Copies"),
		fields: [
			{ fieldname: "paper_set", label: __("Set"), fieldtype: "Select", options: "A\nB", default: "A", reqd: 1 },
			{ fieldname: "room", label: __("Exam Hall"), fieldtype: "Link", options: "Room", reqd: 1,
				get_query: () => ({ filters: { oc_room_type: "Exam Hall", oc_company: frm.doc.company } }) },
			{ fieldname: "copies", label: __("Copies"), fieldtype: "Int", reqd: 1 },
		],
		primary_action_label: __("Record"),
		primary_action(values) {
			frappe.call({ method: `${QP_API}.record_print`, args: { question_paper: frm.doc.name, ...values } }).then((r) => {
				dialog.hide();
				frappe.show_alert({ message: __("{0} copies recorded for this hall", [r.message]), indicator: "green" });
			});
		},
	});
	dialog.show();
}
