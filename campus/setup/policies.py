"""PR-02 Pilot approval policies: the policies the core path needs, from the profile. A document type that already has a
policy (the migrate seeds or the college's own) is left alone."""

import frappe


def ensure_policies(profile, out):
	for spec in profile.get("approval_policies", []):
		document_type = spec["document_type"]
		if not frappe.db.exists("DocType", document_type) or frappe.db.exists("Approval Policy", {"document_type": document_type}):
			continue
		missing = [lv["approver"] for lv in spec["levels"] if lv["approver_type"] == "Position" and not frappe.db.exists("Position", lv["approver"])]
		if missing:
			out.notes.append(f"Approval policy {spec['policy_name']} skipped: position {', '.join(missing)} does not exist.")
			continue
		frappe.get_doc({"doctype": "Approval Policy", **spec}).insert(ignore_permissions=True)
		out.created["Approval Policy"] += 1
