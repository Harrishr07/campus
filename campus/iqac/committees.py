"""M01-04 Committee compliance: meetings held in a period against the Body Type's minimum per year, and the composition rules."""

import math

import frappe
from frappe import _
from frappe.utils import date_diff

from campus.academic_governance import api as governance

YEAR_DAYS = 365


def meeting_status(required, held):
	if not required:
		return "No minimum set"
	return "Compliant" if held >= required else "Below minimum"


def meetings_required(per_year, from_date, to_date):
	"""The Body Type's yearly minimum prorated to the period's length, rounded up, at least one when a minimum is set.

	The days after the first are counted, so a full year (365 or 366 days) or half year needs exactly its share."""
	elapsed = date_diff(to_date, from_date)
	if elapsed < 0:
		frappe.throw(_("From must be on or before To."))
	if not per_year:
		return 0
	return max(1, math.ceil(per_year * elapsed / YEAR_DAYS - 1e-9))


def compliance_rows(company, from_date, to_date):
	"""One row per enabled Body of the company: required (prorated to the period), held, status and unmet composition rules."""
	bodies = governance.committee_bodies(company)
	held = governance.meetings_held(bodies and [b.name for b in bodies], from_date, to_date)
	return [
		{
			"body": body.name, "body_type": body.body_type, "required": (required := meetings_required(body.min_meetings_per_year, from_date, to_date)),
			"held": held.get(body.name, 0),
			"status": meeting_status(required, held.get(body.name, 0)),
			"composition": "; ".join(s.rule for s in governance.composition_shortfalls(body.name, to_date)),
		}
		for body in bodies
	]  # fmt: skip
