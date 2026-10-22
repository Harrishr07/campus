"""M06-02 Why a hall ticket is withheld: a pure rule over the registration's facts.

Debarment withholds outright. Attendance shortage (SA) and detention bar only the term's courses, so they withhold
only when no eligible course is left: an SA or detained student still sits the eligible arrears (R2022 cl. 15.1).
An unconfirmed registration and unpaid exam dues withhold too. An empty list means the ticket is issued.
"""

from frappe import _


def withheld_reasons(*, confirmed, dues, debarred, detained, shortage, eligible_courses):
	"""Reasons (list of strings) to withhold the ticket. `debarred` / `detained` are the flag reasons or None."""
	reasons = eligibility_reasons(debarred, detained, shortage, eligible_courses)
	if not confirmed:
		reasons.append(_("Exam registration not confirmed"))
	if dues > 0:
		reasons.append(_("Unpaid exam dues of {0}").format(f"{dues:,.2f}"))
	return reasons


def eligibility_reasons(debarred, detained, shortage, eligible_courses):
	if debarred:
		return [_("Debarred: {0}").format(debarred)]
	if eligible_courses:
		return []
	reasons = []
	if shortage:
		reasons.append(_("Attendance shortage (SA)"))
	if detained:
		reasons.append(_("Detained: {0}").format(detained))
	return reasons or [_("No course is eligible for the examination")]
