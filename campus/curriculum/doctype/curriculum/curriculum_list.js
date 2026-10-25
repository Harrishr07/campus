frappe.listview_settings["Curriculum"] = {
	get_indicator(doc) {
		const colors = {
			Draft: "orange",
			Approved: "green",
			Effective: "blue",
			Superseded: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
