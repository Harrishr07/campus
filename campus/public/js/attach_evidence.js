// M01-01 Attach as Evidence on every document type listed in Campus Settings > Evidence Sources.
frappe.provide("campus.evidence");

campus.evidence.sources = function () {
	campus.evidence._sources =
		campus.evidence._sources || frappe.xcall("campus.iqac.api.evidence_source_doctypes");
	return campus.evidence._sources;
};

$(document).on("form-refresh", (event, frm) => {
	if (frm.is_new() || frm.doctype === "Evidence" || frm.doc.docstatus === 2) return;
	if (
		!frappe.user.has_role("IQAC Coordinator") &&
		!frappe.user.has_role("IQAC Criterion Owner") &&
		!frappe.user.has_role("System Manager")
	)
		return;
	campus.evidence.sources().then((sources) => {
		if (!(frm.doctype in sources)) return;
		frm.add_custom_button(
			__("Attach as Evidence"),
			() => campus.evidence.dialog(frm, sources[frm.doctype]),
			__("Actions")
		);
	});
});

campus.evidence.dialog = function (frm, file_field) {
	const fields = [
		{
			fieldname: "title",
			fieldtype: "Data",
			label: __("Title"),
			reqd: 1,
			default: frm.doc.title || frm.doc.name,
		},
		{
			fieldname: "evidence_type",
			fieldtype: "Select",
			label: __("Type"),
			reqd: 1,
			default: "Other",
			options:
				"IQAC Minutes\nAcademic Calendar\nAQAR\nFeedback Report\nBest Practice\nOther",
		},
		{
			fieldname: "academic_year",
			fieldtype: "Link",
			options: "Academic Year",
			label: __("Academic Year"),
			reqd: 1,
			default: frm.doc.academic_year,
		},
		{ fieldname: "is_public", fieldtype: "Check", label: __("Public (needs a public file)") },
	];
	if (!file_field) {
		fields.push(
			{ fieldname: "file", fieldtype: "Attach", label: __("File") },
			{ fieldname: "url", fieldtype: "Data", options: "URL", label: __("or URL") }
		);
	}
	fields.push({
		fieldname: "nodes",
		fieldtype: "Table",
		label: __("Evidence For"),
		cannot_add_rows: false,
		fields: [
			{
				fieldname: "node",
				fieldtype: "Link",
				options: "Framework Node",
				label: __("Node"),
				in_list_view: 1,
				reqd: 1,
			},
			{
				fieldname: "slot_name",
				fieldtype: "Data",
				label: __("Slot"),
				in_list_view: 1,
				reqd: 1,
			},
		],
	});
	frappe.prompt(
		fields,
		(values) =>
			frappe
				.xcall("campus.iqac.api.attach_as_evidence", {
					doctype: frm.doctype,
					name: frm.docname,
					...values,
					nodes: values.nodes || [],
				})
				.then((name) => frappe.set_route("Form", "Evidence", name)),
		__("Attach as Evidence")
	);
};
