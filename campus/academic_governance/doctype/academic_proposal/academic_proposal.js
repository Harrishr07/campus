frappe.ui.form.on("Academic Proposal", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Submit to Route"), () =>
				frm.call("submit_to_route").then(() => frm.reload_doc())
			).addClass("btn-primary");
		}
		if (frm.doc.status === "In Route") {
			frm.add_custom_button(__("Advance Stage"), () =>
				frm.call("advance_stage").then(() => frm.reload_doc())
			).addClass("btn-primary");
			frm.dashboard.set_headline(
				__("Awaiting a resolution of {0} (stage {1})", [
					frm.doc.current_body_type,
					frm.doc.current_stage,
				])
			);
		}
		frm.set_query("curriculum", () => ({
			filters: {
				status: ["in", ["Draft", "Approved"]],
				...(frm.doc.regulation ? { regulation: frm.doc.regulation } : {}),
			},
		}));
	},
});
