"""M02-02 Academic Proposal stage logic: which resolution lets a proposal leave its current stage, and the audit trail.

A stage is passed only by a resolution on the proposal in a quorate meeting of a Body of the stage's Body Type (the
proposal's company; a Board of Studies only of the proposal's department), decided Approved or Rejected, not void, and
held no earlier than the previous stage's resolution.
"""

import json

import frappe

# Bodies of these types are per department: only the proposal's own department's body can decide it.
DEPARTMENT_BODY_TYPES = ("Board of Studies",)


def find_resolution(proposal, body_type, not_before=None):
	"""The latest qualifying resolution of `body_type` on `proposal` (a dict), or None."""
	rows = frappe.db.sql(
		"""select r.resolution_no, r.decision, m.name as body_meeting, m.body, m.meeting_date as resolution_date
		from `tabMeeting Resolution` r
		join `tabBody Meeting` m on m.name = r.parent and r.parenttype = 'Body Meeting'
		join `tabBody` b on b.name = m.body
		where r.proposal = %(proposal)s and r.void = 0 and r.decision in ('Approved', 'Rejected')
			and m.status != 'Cancelled' and m.quorum_status = 'Met' and m.docstatus < 2
			and b.body_type = %(body_type)s and b.company = %(company)s
			and (b.department = %(department)s or (ifnull(b.department, '') = '' and %(per_department)s = 0))
			and (%(not_before)s is null or m.meeting_date >= %(not_before)s)
		order by m.meeting_date desc, r.creation desc, r.idx desc limit 1""",
		{"proposal": proposal.name, "body_type": body_type, "company": proposal.company,
		 "department": proposal.department or "", "per_department": int(body_type in DEPARTMENT_BODY_TYPES), "not_before": not_before},
		as_dict=True,
	)  # fmt: skip
	return rows[0] if rows else None


@frappe.whitelist()
def audit_trail(proposal):
	"""The comments and document versions of a proposal, for IQAC and anyone else who may read it."""
	frappe.has_permission("Academic Proposal", "read", doc=proposal, throw=True)
	comments = frappe.get_all(
		"Comment",
		{"reference_doctype": "Academic Proposal", "reference_name": proposal, "comment_type": "Comment"},
		["name", "owner", "creation", "content"],
		order_by="creation",
	)
	versions = []
	for version in frappe.get_all(
		"Version",
		{"ref_doctype": "Academic Proposal", "docname": proposal},
		["name", "owner", "creation", "data"],
		order_by="creation",
	):
		data = json.loads(version.data or "{}")
		versions.append(
			{
				"name": version.name,
				"owner": version.owner,
				"creation": version.creation,
				"changed": data.get("changed", []),
				"data": data,
			}
		)
	return {"comments": comments, "versions": versions}
