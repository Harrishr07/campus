"""M04-02 Eligibility evaluation from Eligibility Rule records.

Percentage is total obtained / total maximum over the rule's required subjects (over all entered
subjects when the rule lists none). Subjects match case-insensitively. A category without a row in the
rule has no minimum.
"""

import frappe
from frappe import _
from frappe.utils import flt


def subject_lines(text):
	return [s.strip() for s in (text or "").replace(",", "\n").splitlines() if s.strip()]


def check_eligibility(required, minimums, marks, category, exam=None):
	"""Pure rule check. `marks` is [(subject, max, obtained)], `minimums` {category: min %}. Returns reasons."""
	if not marks:
		return [_("No qualifying marks entered.")]
	by_subject = {s.strip().lower(): (m, o) for s, m, o in marks}
	reasons = [_("Subject {0} is missing from the qualifying marks.").format(s)
		for s in required if s.strip().lower() not in by_subject]  # fmt: skip
	counted = [by_subject[s.strip().lower()] for s in required if s.strip().lower() in by_subject] or (
		[] if required else list(by_subject.values())
	)
	total = sum(m for m, _o in counted)
	percent = sum(o for _m, o in counted) * 100 / total if total else 0
	if minimums:
		reasons += minimum_reasons(minimums, category, percent, exam)
	return reasons


def minimum_reasons(minimums, category, percent, exam):
	if not category:
		return [_("Student category is not set; the minimum marks depend on it.")]
	if category in minimums and percent < minimums[category]:
		return [_("{0} marks of {1:.2f}% are below the {2}% required for category {3}.").format(
			exam or _("Qualifying"), percent, flt(minimums[category]), category)]  # fmt: skip
	return []


def find_rule(program):
	name = frappe.db.get_value(
		"Eligibility Rule", {"program": program, "enabled": 1}, "name", order_by="modified desc"
	)
	return frappe.get_doc("Eligibility Rule", name) if name else None


def evaluate(applicant):
	"""Evaluate `applicant` (name) against its program's rule; store and return {eligible, reasons}."""
	doc = frappe.get_doc("Student Applicant", applicant)
	rule = find_rule(doc.program)
	if not rule:
		return {"eligible": False, "reasons": [_("No Eligibility Rule for program {0}.").format(doc.program)]}
	marks = [(r.subject, flt(r.max_marks), flt(r.obtained_marks)) for r in doc.oc_qualifying_marks]
	minimums = {r.student_category: flt(r.min_percent) for r in rule.category_marks}
	reasons = check_eligibility(
		subject_lines(rule.required_subjects), minimums, marks, doc.student_category, rule.qualifying_exam
	)
	status = "Ineligible" if reasons else "Eligible"
	frappe.db.set_value(
		"Student Applicant", doc.name,
		{"oc_eligibility_status": status, "oc_eligibility_reasons": "\n".join(reasons) or None},
		update_modified=False,
	)  # fmt: skip
	return {"eligible": not reasons, "reasons": reasons}
