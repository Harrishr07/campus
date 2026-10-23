frappe.ui.form.on("Publication", {
	doi(frm) {
		if (!frm.doc.doi || frm.doc.title) return;
		frm.call("fill_from_crossref").then(() => frm.refresh());
	},
	refresh(frm) {
		if (frm.doc.doi && !frm.is_new()) {
			frm.add_web_link(`https://doi.org/${frm.doc.doi}`, __("Open DOI"));
		}
	},
});
