frappe.ui.form.on("University Exam Registration Batch", {
	setup(frm) {
		frm.set_query("exam_session", () => ({ filters: { examination_mode: "Affiliated" } }));
		frm.set_query("export_format", () => ({
			filters: {
				direction: "Export",
				...(frm.doc.company ? { company: ["in", [frm.doc.company, ""]] } : {}),
			},
		}));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args = {}) =>
			frappe.call({
				method: `campus.examinations.university_export.${method}`,
				args: { name: frm.doc.name, ...args },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		const ask = (method, title, reference, date) =>
			frappe.prompt(
				[
					{ fieldname: "reference", fieldtype: "Data", label: __(reference), reqd: 1 },
					{
						fieldname: "on",
						fieldtype: "Date",
						label: __(date),
						reqd: 1,
						default: frappe.datetime.get_today(),
					},
				],
				(values) =>
					call(method, {
						reference: values.reference,
						[method === "record_transmission" ? "transmitted_on" : "acknowledged_on"]:
							values.on,
					}),
				__(title)
			);
		const status = frm.doc.status;
		if (status === "Building") {
			frm.set_intro(
				__("The rows are being built in the background. Reload to see them."),
				"blue"
			);
			frm.add_custom_button(__("Reload"), () => frm.reload_doc());
		}
		if (status === "Draft") {
			frm.add_custom_button(__("Build Rows"), () =>
				call("build_rows").then(() =>
					frappe.show_alert({
						message: __("Building the rows in the background"),
						indicator: "blue",
					})
				)
			);
			frm.add_custom_button(__("Export"), () => call("export")).addClass("btn-primary");
		}
		if (status === "Exported") {
			frm.add_custom_button(__("Record Transmission"), () =>
				ask(
					"record_transmission",
					"Transmission",
					"Transmission Reference",
					"Transmitted On"
				)
			);
		}
		if (status === "Transmitted") {
			frm.add_custom_button(__("Record Acknowledgement"), () =>
				ask(
					"record_acknowledgement",
					"Acknowledgement",
					"Acknowledgement Reference",
					"Acknowledged On"
				)
			);
		}
		if (["Acknowledged", "Partly Rejected"].includes(status)) {
			frm.add_custom_button(__("Re-export Corrections"), () => call("reexport"));
		}
	},
});
