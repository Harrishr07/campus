"""M02-03 Quorum rule: at least quorum_percent of the members in office must attend (rounded up, never fewer than
one), and at least one member of every category the Body Type marks mandatory for quorum. Pure functions over the
members in office on the meeting date (campus.academic_governance.api.members_in_office), so unit-testable."""

import math

import frappe


def member_key(row):
	return row.employee or row.external_member


def quorum_status(quorum_percent, mandatory_categories, in_office, present_keys):
	"""frappe._dict(met, required, present, in_office, missing_categories). Attendees not in office are ignored."""
	present_keys = set(present_keys)
	attending = [m for m in in_office if member_key(m) in present_keys]
	required = max(1, math.ceil(len(in_office) * (quorum_percent or 0) / 100))
	attending_categories = {m.category for m in attending}
	missing = [c for c in mandatory_categories if c not in attending_categories]
	return frappe._dict(
		met=len(attending) >= required and not missing,
		required=required,
		present=len(attending),
		in_office=len(in_office),
		missing_categories=missing,
	)
