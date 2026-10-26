"""M07-04 / M07-05 Self-appraisal: a teacher's API (academic performance) score from the API Score Rule in force, written as KRA
scores on an HRMS Appraisal, reviewed by the HOD through the approval engine.

Inputs for an Appraisal Cycle: FDPs the teacher attended (HRMS Training Event flagged oc_is_fdp, attendance Present; read from
the event, never copied), verified Faculty Achievements, and teaching workload (the average weekly hours of the year's
submitted Course Allocations). Publications and student feedback arrive in Phase 3: `phase3_quantity` is their hook.

The Appraisal is the HRMS one, rated manually: its Goals carry the computed star scores, and while a draft they are
recomputed on every save, so they cannot be edited by hand. Submitting goes only through an Appraisal Review that the
department HOD approves (never the appraisee); a submitted Appraisal cannot be changed.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.api import find_policy, latest_request, resolve_position, start_request
from campus.faculty import api_scoring, workload

HR_ROLES = ("System Manager", "HR Manager", "HR User")
FDP, WORKLOAD = "FDP Attended", "Teaching Workload"
PHASE_THREE = ("Publication", "Student Feedback")


def is_hr(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(HR_ROLES) & set(frappe.get_roles(user)))


def rule_in_force(company, on_date):
	"""API Score Rule document in force for `company` on `on_date` (latest Effective From not after it), or None."""
	name = frappe.db.get_value(
		"API Score Rule",
		{"company": company, "effective_from": ["<=", getdate(on_date)]},
		"name",
		order_by="effective_from desc",
	)
	return frappe.get_doc("API Score Rule", name) if name else None


def phase3_quantity(activity, employee, start, end):
	"""Hook for Phase 3 (publications from the research module, student feedback from the feedback module): quantity of
	`activity` by `employee` between `start` and `end`. Returns 0 until those modules exist."""
	return 0


def compute(employee, appraisal_cycle):
	"""The API computation for one teacher and cycle, without saving anything."""
	cycle = frappe.db.get_value(
		"Appraisal Cycle", appraisal_cycle, ["company", "start_date", "end_date"], as_dict=True
	)
	if not cycle:
		frappe.throw(_("Appraisal Cycle {0} does not exist.").format(appraisal_cycle))
	rule = rule_in_force(cycle.company, cycle.end_date)
	if not rule:
		frappe.throw(_("No API Score Rule is in force for {0} on {1}.").format(cycle.company, cycle.end_date))
	year_of = academic_year_of()
	items = activity_items(employee, cycle, year_of)
	results = api_scoring.score_activities(items, rule.rows, year_of)
	return frappe._dict(
		rule=rule, results=results, kras=api_scoring.kra_scores(results, rule.kras), total=sum(r.points for r in results)
	)  # fmt: skip


def academic_year_of():
	"""A function from a date to the Academic Year it falls in (the calendar year when none covers it)."""
	years = frappe.get_all("Academic Year", fields=["name", "year_start_date", "year_end_date"])

	def year_of(on_date):
		on_date = getdate(on_date)
		return next(
			(y.name for y in years if getdate(y.year_start_date) <= on_date <= getdate(y.year_end_date)),
			on_date.year,
		)

	return year_of


def activity_items(employee, cycle, year_of):
	items = [(FDP, d, 1) for d in fdp_dates(employee, cycle)]
	items += [(a.achievement_type, a.achievement_date, 1) for a in verified_achievements(employee, cycle)]
	items += workload_items(employee, cycle, year_of)
	for activity in PHASE_THREE:
		quantity = phase3_quantity(activity, employee, cycle.start_date, cycle.end_date)
		if quantity:
			items.append((activity, getdate(cycle.end_date), quantity))
	return items


def fdp_dates(employee, cycle):
	"""Start dates of the FDPs (submitted Training Events flagged oc_is_fdp) the teacher attended in the cycle."""
	event, attendee = frappe.qb.DocType("Training Event"), frappe.qb.DocType("Training Event Employee")
	rows = (
		frappe.qb.from_(attendee)
		.join(event)
		.on(attendee.parent == event.name)
		.select(event.start_time)
		.where((attendee.employee == employee) & (attendee.attendance == "Present"))
		.where((event.docstatus == 1) & (event.oc_is_fdp == 1) & (event.event_status != "Cancelled"))
		.where((event.start_time >= getdate(cycle.start_date)) & (event.start_time < add_days(getdate(cycle.end_date), 1)))
		.run()
	)  # fmt: skip
	return [getdate(start) for (start,) in rows]


def verified_achievements(employee, cycle):
	return frappe.get_all(
		"Faculty Achievement",
		{
			"employee": employee,
			"verified": 1,
			"achievement_date": ["between", [cycle.start_date, cycle.end_date]],
		},
		["achievement_type", "achievement_date"],
	)


def workload_items(employee, cycle, year_of):
	"""One item per academic year: the average weekly hours over the year's terms in which the teacher teaches."""
	terms = frappe.get_all(
		"Academic Term",
		{"term_start_date": ["between", [cycle.start_date, cycle.end_date]]},
		["name", "term_start_date"],
		order_by="term_start_date",
	)
	by_year = {}
	for term in terms:
		hours = flt(workload.submitted_hours(term.name, cycle.company).get(employee))
		if hours:
			by_year.setdefault(year_of(term.term_start_date), []).append((term.term_start_date, hours))
	return [
		(WORKLOAD, terms_hours[0][0], sum(h for _d, h in terms_hours) / len(terms_hours))
		for terms_hours in by_year.values()
	]


def breakdown_text(computation):
	lines = []
	for r in computation.results:
		note = _("capped, {0} before the annual caps").format(flt(r.raw_points, 2)) if r.capped else ""
		lines.append(
			f"{_(r.activity)}: {flt(r.quantity, 2)} = {flt(r.points, 2)} {_('points')} {note}".strip()
		)
	return "\n".join(lines)


def apply_to(appraisal, computation):
	"""Write the KRA scores of `computation` as the manually rated Goals of a draft Appraisal."""
	appraisal.rate_goals_manually = 1
	appraisal.set("appraisal_kra", [])
	appraisal.set("goals", [])
	for kra in computation.kras:
		appraisal.append("goals", {"kra": kra.kra, "per_weightage": kra.weightage, "score": kra.score})
	appraisal.oc_api_rule = computation.rule.name
	appraisal.oc_api_total = flt(computation.total, 2)
	appraisal.oc_api_breakdown = breakdown_text(computation)
	appraisal.flags.api_applied = True


def check_may_act_for(employee):
	"""The appraisee, or HR."""
	if not is_hr() and frappe.db.get_value("Employee", employee, "user_id") != frappe.session.user:
		frappe.throw(_("Only the appraisee or HR can do this."), frappe.PermissionError)


def create_or_update(employee, appraisal_cycle):
	"""Create the teacher's Appraisal for the cycle with the computed KRA scores, or recompute the draft one. Refused once
	the HOD review has been requested (the scores are then frozen) or the HOD has submitted it."""
	check_may_act_for(employee)
	computation = compute(employee, appraisal_cycle)
	appraisal = existing_appraisal(employee, appraisal_cycle) or new_appraisal(employee, appraisal_cycle)
	apply_to(appraisal, computation)
	appraisal.flags.ignore_permissions = (
		True  # the permission check above is the rule; Employee role rights on Appraisal vary
	)
	appraisal.save()
	appraisal.flags.api_applied = False  # later saves of this object are recomputed again
	return appraisal


def existing_appraisal(employee, appraisal_cycle):
	name = frappe.db.get_value(
		"Appraisal", {"employee": employee, "appraisal_cycle": appraisal_cycle, "docstatus": ["<", 2]}
	)
	if not name:
		return None
	appraisal = frappe.get_doc("Appraisal", name, for_update=True)
	if not appraisal.oc_api_rule:
		frappe.throw(
			_("{0} was not made from a self-appraisal; change it in the Appraisal itself.").format(name)
		)
	if appraisal.docstatus:
		frappe.throw(_("{0} is submitted and can no longer be changed.").format(name))
	if frozen_reviews(name):
		frappe.throw(_("{0} is with the HOD for review and its scores are frozen.").format(name))
	return appraisal


def new_appraisal(employee, appraisal_cycle):
	cycle = frappe.db.get_value(
		"Appraisal Cycle", appraisal_cycle, ["company", "start_date", "end_date"], as_dict=True
	)
	return frappe.get_doc(
		{
			"doctype": "Appraisal", "employee": employee, "appraisal_cycle": appraisal_cycle, "company": cycle.company,
			"start_date": cycle.start_date, "end_date": cycle.end_date,
		}
	)  # fmt: skip


def open_reviews(appraisal, lock=False):
	"""Appraisal Reviews of `appraisal` that are not cancelled or rejected (read with FOR UPDATE when `lock`)."""
	review = frappe.qb.DocType("Appraisal Review")
	query = (
		frappe.qb.from_(review)
		.select(review.name)
		.where((review.appraisal == appraisal) & (review.docstatus < 2))
	)
	names = [name for (name,) in (query.for_update() if lock else query).run()]
	return [n for n in names if review_status(n) != rules.REJECTED]


def review_status(review):
	latest = latest_request(frappe._dict(doctype="Appraisal Review", name=review))
	return latest and latest.status


def frozen_reviews(appraisal):
	"""Reviews that hold the scores: pending with the HOD, or approved. A rejected or returned review does not."""
	return [n for n in open_reviews(appraisal) if review_status(n) in (rules.PENDING, rules.APPROVED)]


def request_review(appraisal):
	"""Send the draft Appraisal to its reviewer (the HOD of the appraisee's department, or the Principal when the appraisee
	is an HOD) and return the Appraisal Review name. A returned review is sent again."""
	doc = frappe.get_doc("Appraisal", appraisal, for_update=True)
	check_may_act_for(doc.employee)
	returned = [n for n in open_reviews(doc.name) if review_status(n) == rules.RETURNED]
	review = (
		frappe.get_doc("Appraisal Review", returned[0])
		if returned
		else frappe.get_doc({"doctype": "Appraisal Review", "appraisal": doc.name})
	)
	review.flags.ignore_permissions = (
		True  # the appraisee's rights on the Review are read-only; the check above is the rule
	)
	review.insert() if review.is_new() else review.save()
	if not find_policy(review):
		frappe.throw(_("No approval policy covers Appraisal Review for {0}.").format(review.company))
	request = start_request(review)
	check_has_other_approver(request, review)
	return review.name


def check_has_other_approver(request, review):
	"""Fail now, not at the final approval, when nobody but the appraisee could approve."""
	approvers = frappe.get_all(
		"Approval Request Approver",
		{"parent": request.name, "cycle": request.cycle, "level": request.current_level},
		pluck="user",
	)
	if not [u for u in approvers if u != appraisee_user(review)]:
		frappe.throw(
			_(
				"No reviewer other than the appraisee could be found for {0}. Ask HR to fix the position holders."
			).format(review.appraisal)
		)


def appraisee_user(review):
	return frappe.db.get_value("Employee", review.employee, "user_id")


def set_appraisee_is_hod(review):
	"""The Principal, not the HOD, reviews an appraisee who holds the HOD position of their own department."""
	user = appraisee_user(review)
	review.appraisee_is_hod = int(bool(user) and user in resolve_position("HOD", review.department))


def check_reviewable(review):
	"""A review needs a draft Appraisal made from a self-appraisal, and only one review may be open per Appraisal."""
	appraisal = frappe.db.get_value("Appraisal", review.appraisal, ["docstatus", "oc_api_rule"], as_dict=True)
	if not appraisal.oc_api_rule:
		frappe.throw(_("{0} was not made from a self-appraisal.").format(review.appraisal))
	if appraisal.docstatus != 0:
		frappe.throw(_("{0} is already submitted.").format(review.appraisal))
	frappe.db.get_value(
		"Appraisal", review.appraisal, "name", for_update=True
	)  # serialises requests for one Appraisal
	if [r for r in open_reviews(review.appraisal, lock=True) if r != review.name]:
		frappe.throw(_("{0} already has a review in progress.").format(review.appraisal))


def check_not_appraisee(review):
	"""No self-approval: the appraisee cannot take the final approval of their own appraisal, whatever position they hold."""
	if appraisee_user(review) == frappe.session.user:
		frappe.throw(_("You cannot approve your own appraisal."))


def submit_appraisal(review):
	appraisal = frappe.get_doc("Appraisal", review.appraisal)
	appraisal.flags.from_review = True
	appraisal.flags.ignore_permissions = True
	appraisal.submit()


# Doc events of the HRMS Appraisal (hooks.py)


def before_validate(appraisal, method=None):
	"""Draft Appraisals made from a self-appraisal take their Goals from the rule, so hand edits are overwritten. While a
	review holds them (pending or approved) the scores are frozen and only HR can save, and only unchanged."""
	if (
		not appraisal.oc_api_rule
		or appraisal.docstatus != 0
		or appraisal.flags.api_applied
		or appraisal.flags.from_review
		or appraisal.is_new()
	):
		return
	if frozen_reviews(appraisal.name):
		if not is_hr():
			check_scores_unchanged(appraisal)
		return
	apply_to(appraisal, compute(appraisal.employee, appraisal.appraisal_cycle))


def scores_of(appraisal):
	goals = [(g.kra, flt(g.per_weightage, 2), flt(g.score, 2)) for g in appraisal.goals]
	return goals, appraisal.oc_api_rule, flt(appraisal.oc_api_total, 2), appraisal.oc_api_breakdown or ""


def check_scores_unchanged(appraisal):
	stored = frappe.get_doc("Appraisal", appraisal.name)
	if scores_of(stored) != scores_of(appraisal):
		frappe.throw(_("The scores of {0} are frozen while the HOD review is open.").format(appraisal.name))


def before_submit(appraisal, method=None):
	"""A self-appraisal is submitted by the review's approval. HR may submit it directly with a recorded reason, but not their own."""
	if not appraisal.oc_api_rule or appraisal.flags.from_review:
		return
	reason = (appraisal.oc_api_override_reason or "").strip()
	user = frappe.session.user
	if is_hr() and reason and frappe.db.get_value("Employee", appraisal.employee, "user_id") != user:
		appraisal.oc_api_override_by = user
		return
	frappe.throw(
		_(
			"A self-appraisal is submitted by the HOD's approval of its Appraisal Review; HR can submit it directly with an override reason."
		)
	)


def block_feedback_on_self_appraisal(feedback, method=None):
	"""Employee Performance Feedback moves the Appraisal's final score, so it cannot touch a submitted self-appraisal (HR may)."""
	if not feedback.appraisal or is_hr():
		return
	appraisal = frappe.db.get_value(
		"Appraisal", feedback.appraisal, ["oc_api_rule", "docstatus"], as_dict=True
	)
	if appraisal and appraisal.oc_api_rule and appraisal.docstatus == 1:
		frappe.throw(
			_("{0} is a submitted self-appraisal and its score can no longer change.").format(
				feedback.appraisal
			)
		)


def has_permission(doc, ptype=None, user=None):
	"""Deny-only hook: once the HOD's approval has submitted a self-appraisal Appraisal, only HR can change or cancel it."""
	if doc.get("oc_api_rule") and doc.docstatus == 1 and ptype in ("write", "delete", "cancel", "amend"):
		return is_hr(user or frappe.session.user)
	return True
