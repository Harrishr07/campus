frappe.ui.form.on("Metric Value", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args) => frappe.xcall("campus.iqac.api." + method, args).then(() => frm.reload_doc());
		frm.add_custom_button(__("Drill-down"), () =>
			frappe.set_route("query-report", "Metric Drill-down", { metric_value: frm.doc.name })
		);
		if (["Draft", "Computed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Verify"), () => call("verify_metric", { metric_value: frm.doc.name }));
			if (frm.doc.computed_at) {
				frm.add_custom_button(__("Request Override"), () => request_override(frm));
			}
		}
		if (frm.doc.status === "Verified") {
			frm.add_custom_button(__("Reopen"), () => call("reopen_metric", { metric_value: frm.doc.name }));
		}
		if (frm.doc.source_changed) {
			frm.dashboard.set_headline_alert(
				__("Source changed: recomputing now gives {0}; this {1} value was not touched.", [
					format_number(frm.doc.recomputed_value, null, 2),
					__(frm.doc.status),
				]),
				"orange"
			);
		}
		show_word_count(frm);
		show_evidence_slots(frm);
	},
	narrative(frm) {
		show_word_count(frm);
	},
});

function request_override(frm) {
	frappe.prompt(
		[
			{ fieldname: "proposed_value", fieldtype: "Float", label: __("Proposed Value"), reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		(values) =>
			frappe
				.xcall("campus.iqac.api.request_override", { metric_value: frm.doc.name, ...values })
				.then((name) => frappe.set_route("Form", "Metric Override", name)),
		__("Request Override")
	);
}

function show_word_count(frm) {
	const field = frm.get_field("narrative");
	if (!field || !field.$wrapper) return;
	const words = (frm.doc.narrative || "")
		.replace(/<[^>]*>/g, " ")
		.replace(/&nbsp;/g, " ")
		.split(/\s+/)
		.filter(Boolean).length;
	frappe.db.get_value("Framework Node", frm.doc.node, "word_limit").then(({ message }) => {
		const limit = message && message.word_limit;
		const over = limit && words > limit;
		field.set_description(
			limit ? __("{0} of {1} words", [words, limit]) : __("{0} words", [words])
		);
		field.$wrapper.find(".help-box").css("color", over ? "var(--red-500)" : "");
	});
}

function show_evidence_slots(frm) {
	frappe.xcall("campus.iqac.api.evidence_slot_status", { cycle: frm.doc.cycle, node: frm.doc.node }).then((slots) => {
		if (!slots.length) return;
		const rows = slots
			.map((slot) => {
				const state = slot.filled
					? `<span class="indicator-pill green">${__("Filled")}</span> ${slot.evidence.map((e) => frappe.utils.escape_html(e)).join(", ")}`
					: `<span class="indicator-pill ${slot.required ? "red" : "orange"}">${__("Missing")}</span>`;
				return `<tr><td>${frappe.utils.escape_html(slot.slot_name)}</td><td>${__(slot.kind)}</td><td>${state}</td></tr>`;
			})
			.join("");
		frm.dashboard.add_section(`<table class="table table-sm"><tbody>${rows}</tbody></table>`, __("Evidence"));
	});
}
