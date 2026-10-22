"""M07-01 Qualification check against the Faculty Norm in force.

Employee (appointment): a teacher whose cadre requirements are not met can only be saved by the Principal of the
company with an override reason. The check runs when the employee is new or a qualification fact or the reason
changed; other edits keep the earlier override, so a later stricter norm only re-flags (shortfall text) and never
blocks unrelated HR edits. Job Applicant: flagged only (shortfall text), since nobody is appointed yet.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from campus.campus_platform.api import resolve_position
from campus.faculty.norms import cadre_rule
from campus.faculty.setup import QUALIFICATIONS

FACTS = (
	"company", "date_of_joining", "oc_staff_type", "oc_cadre", "oc_highest_qualification", "oc_phd_status",
	"oc_net_set", "oc_prior_teaching_experience", "oc_qualification_override_reason",
)  # fmt: skip


def qualification_shortfalls(profile, rule):
	"""Messages for each requirement of the cadre `rule` (Faculty Norm Cadre row) that `profile` does not meet."""
	if not rule:
		return []
	failures = []
	if rank(profile.oc_highest_qualification) < rank(rule.minimum_qualification):
		failures.append(_("Highest qualification {0} is below the required {1}.").format(
			_(profile.oc_highest_qualification or "not recorded"), _(rule.minimum_qualification)))  # fmt: skip
	has_phd = profile.oc_phd_status == "Awarded"
	if rule.requires_phd and not has_phd:
		failures.append(_("A PhD is required."))
	if rule.requires_net_set_or_phd and not (has_phd or profile.oc_net_set):
		failures.append(_("NET / SET / SLET or a PhD is required."))
	if flt(profile.oc_prior_teaching_experience) < flt(rule.minimum_experience_years):
		failures.append(_("{0} years of teaching experience are required; {1} recorded.").format(
			flt(rule.minimum_experience_years), flt(profile.oc_prior_teaching_experience)))  # fmt: skip
	return failures


def validate_employee(doc, method=None):
	sync_phd_qualification(doc)
	failures = employee_shortfalls(doc)
	doc.oc_qualification_shortfall = "\n".join(failures) or None
	before = doc.get_doc_before_save()
	if not failures:
		doc.oc_qualification_override_reason = doc.oc_qualification_override_by = None
	elif before and not any(changed(before, doc, f) for f in FACTS):
		doc.oc_qualification_override_by = before.oc_qualification_override_by  # never set from the client
	else:
		require_principal_override(doc, failures)


def validate_job_applicant(doc, method=None):
	company = doc.job_title and frappe.db.get_value("Job Opening", doc.job_title, "company")
	rule = cadre_rule(company, doc.oc_cadre, today()) if company and doc.oc_cadre else None
	doc.oc_qualification_shortfall = "\n".join(qualification_shortfalls(doc, rule)) or None


def employee_shortfalls(doc):
	if doc.oc_staff_type != "Teaching" or not doc.oc_cadre:
		return []
	return qualification_shortfalls(doc, cadre_rule(doc.company, doc.oc_cadre, doc.date_of_joining or today()))


def require_principal_override(doc, failures):
	if not doc.oc_qualification_override_reason:
		frappe.throw(
			_("{0} does not meet the Faculty Norm for {1}:<br>{2}<br>The Principal must enter an override reason to appoint.").format(
				doc.employee_name or doc.first_name, _(doc.oc_cadre), "<br>".join(failures)),
			title=_("Qualification Below Norm"),
		)  # fmt: skip
	if frappe.session.user not in resolve_position("PRINCIPAL", doc.company):
		frappe.throw(_("Only the Principal of {0} can override the qualification check.").format(doc.company), frappe.PermissionError)
	doc.oc_qualification_override_by = frappe.session.user


def sync_phd_qualification(doc):
	"""An awarded PhD is a Doctorate; a Doctorate without an awarded PhD is a data error."""
	if doc.oc_phd_status == "Awarded":
		doc.oc_highest_qualification = "Doctorate"
	elif doc.oc_highest_qualification == "Doctorate":
		frappe.throw(_("Set PhD Status to Awarded for a Doctorate."))


def changed(before, doc, fieldname):
	old, new = before.get(fieldname), doc.get(fieldname)
	if fieldname == "date_of_joining":
		return getdate(old) != getdate(new)
	if fieldname == "oc_prior_teaching_experience":
		return flt(old) != flt(new)
	return (old or None) != (new or None)


def rank(qualification):
	return QUALIFICATIONS.index(qualification) + 1 if qualification in QUALIFICATIONS else 0
