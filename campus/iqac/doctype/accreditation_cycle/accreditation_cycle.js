frappe.ui.form.on("Accreditation Cycle", {
	setup(frm) {
		frm.set_query("framework", () => ({ filters: { status: "Published" } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const status = frm.doc.status;
		const call = (method, args, done) =>
			frappe.xcall("campus.iqac.api." + method, args).then((result) => {
				if (done) done(result);
				else frm.reload_doc();
			});
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Compute"), () =>
				call("compute_cycle", { cycle: frm.doc.name }, (values) => {
					frappe.show_alert({
						message: __("{0} metric(s) computed", [values.length]),
						indicator: "green",
					});
					frappe.set_route("List", "Metric Value", { cycle: frm.doc.name });
				})
			);
			frm.add_custom_button(__("Compute All (Background)"), () =>
				call("compute_all", { cycle: frm.doc.name }, () =>
					frappe.show_alert({
						message: __("Computation queued; see Bulk Run"),
						indicator: "blue",
					})
				)
			);
			frm.add_custom_button(__("Prepare Values"), () =>
				call("prepare_values", { cycle_name: frm.doc.name }, (names) =>
					frappe.show_alert({
						message: __("{0} value(s) prepared", [names.length]),
						indicator: "green",
					})
				)
			);
		}
		const next = {
			Collecting: __("Move to Validating"),
			Validating: __("Move to IQAC Review"),
			Approved: __("Mark Submitted"),
		}[status];
		if (status === "Validating") {
			frm.add_custom_button(__("Run Validation"), () =>
				call("run_validation", { cycle: frm.doc.name }, (run) =>
					frappe.set_route("Form", "Validation Run", run)
				)
			);
			frm.add_custom_button(__("Readiness"), () =>
				frappe.set_route("query-report", "Cycle Readiness", { cycle: frm.doc.name })
			);
		}
		if (status === "Validating") {
			frm.add_custom_button(next, () =>
				frappe
					.xcall("campus.iqac.api.validation_counts", { cycle: frm.doc.name })
					.then((found) => {
						if (!found.warnings || found.blocking)
							return call("advance_cycle", { cycle_name: frm.doc.name });
						frappe.prompt(
							{
								fieldname: "comment",
								fieldtype: "Small Text",
								label: __("Comment on the {0} warning(s)", [found.warnings]),
								reqd: 1,
							},
							(values) =>
								call("advance_cycle", {
									cycle_name: frm.doc.name,
									comment: values.comment,
								}),
							__("Validation Warnings")
						);
					})
			);
		} else if (next)
			frm.add_custom_button(next, () => call("advance_cycle", { cycle_name: frm.doc.name }));
		if (["Validating", "IQAC Review"].includes(status)) {
			frm.add_custom_button(__("Reopen for Collecting"), () =>
				call("reopen_cycle", { cycle_name: frm.doc.name })
			);
		}
		frm.page.set_indicator(
			__(status),
			{
				Collecting: "blue",
				Validating: "orange",
				"IQAC Review": "yellow",
				Approved: "green",
				Submitted: "green",
			}[status]
		);
	},
});
