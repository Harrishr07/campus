"""M01-04 Committee compliance: meetings held in a period against the Body Type's minimum per year, and the composition rules."""

from campus.academic_governance import api as governance


def meeting_status(required, held):
	if not required:
		return "No minimum set"
	return "Compliant" if held >= required else "Below minimum"


def compliance_rows(company, from_date, to_date):
	"""One row per enabled Body of the company: required, held, status and unmet composition rules."""
	bodies = governance.committee_bodies(company)
	held = governance.meetings_held(bodies and [b.name for b in bodies], from_date, to_date)
	return [
		{
			"body": body.name, "body_type": body.body_type, "required": body.min_meetings_per_year or 0,
			"held": held.get(body.name, 0),
			"status": meeting_status(body.min_meetings_per_year, held.get(body.name, 0)),
			"composition": "; ".join(s.rule for s in governance.composition_shortfalls(body.name, to_date)),
		}
		for body in bodies
	]  # fmt: skip
