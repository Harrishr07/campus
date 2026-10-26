// M17-03 Approval panel for any form whose controller uses ApprovableDocument (data from __onload.approval).
frappe.provide("campus.approvals");

campus.approvals.METHOD = "campus.campus_platform.approvals.";

campus.approvals.render = function (frm) {
	const info = frm.doc.__onload && frm.doc.__onload.approval;
	if (!info || frm.is_new()) return;
	if (info.trail && info.trail.length) {
		frm.dashboard.add_section(campus.approvals.trail_html(info), __("Approval Trail"));
	}
	if (info.status) {
		frm.dashboard.add_indicator(
			__("Approval: {0}", [__(info.status)]),
			campus.approvals.color(info.status)
		);
	}
	if (info.can_request && !frm.is_dirty()) {
		frm.add_custom_button(__("Request Approval"), () =>
			campus.approvals.call(frm, "request_approval", {
				doctype: frm.doctype,
				name: frm.docname,
			})
		);
	}
	if (info.can_act) {
		const group = __("Approval");
		frm.add_custom_button(
			__("Approve"),
			() => campus.approvals.act(frm, info, "approve", false),
			group
		);
		frm.add_custom_button(
			__("Reject"),
			() => campus.approvals.act(frm, info, "reject", true),
			group
		);
		frm.add_custom_button(
			__("Return for Changes"),
			() => campus.approvals.act(frm, info, "return_for_changes", true),
			group
		);
	}
};

campus.approvals.act = function (frm, info, method, comment_required) {
	frappe.prompt(
		[
			{
				fieldname: "comment",
				fieldtype: "Small Text",
				label: __("Comment"),
				reqd: comment_required ? 1 : 0,
			},
		],
		(values) =>
			campus.approvals.call(frm, method, { request: info.request, comment: values.comment }),
		__("Approval")
	);
};

campus.approvals.call = function (frm, method, args) {
	frappe
		.call({ method: campus.approvals.METHOD + method, args, freeze: true })
		.then(() => frm.reload_doc());
};

campus.approvals.color = function (status) {
	return (
		{ Pending: "orange", Approved: "green", Rejected: "red", Returned: "yellow" }[status] ||
		"gray"
	);
};

campus.approvals.trail_html = function (info) {
	const rows = info.trail.map((row) => {
		const by = row.on_behalf_of
			? __("{0} on behalf of {1}", [
					frappe.user.full_name(row.approver),
					frappe.user.full_name(row.on_behalf_of),
			  ])
			: frappe.user.full_name(row.approver);
		const comment = row.comment ? ` - ${frappe.utils.escape_html(row.comment)}` : "";
		const level = row.level ? __("Level {0}", [row.level]) : "";
		return `<div class="small">${frappe.datetime.str_to_user(row.timestamp)} &middot; ${level}
			<b>${__(row.action)}</b> &middot; ${frappe.utils.escape_html(by)}${comment}</div>`;
	});
	return `<div class="approval-trail">${rows.join("")}</div>`;
};

frappe.ui.form.on("*", {
	refresh(frm) {
		campus.approvals.render(frm);
	},
});
