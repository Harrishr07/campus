"""M02-04 Student -> regulation resolution, auto-assignment and the guarded regulation change."""

import frappe
from frappe import _
from frappe.utils import today

from campus.campus_platform.regulation_setup import DEAN_ROLE


def resolve_regulation(company, program, batch):
	"""Effective regulation of `company` covering `program` whose effective-from year is the latest
	one not after the admission year `batch` (compared by Academic Year start date). None if absent."""
	batch_start = frappe.db.get_value("Academic Year", batch, "year_start_date") if batch else None
	if not (company and program and batch_start):
		return None
	regulation = frappe.qb.DocType("Regulation")
	covered = frappe.qb.DocType("Regulation Program")
	year = frappe.qb.DocType("Academic Year")
	rows = (
		frappe.qb.from_(regulation)
		.join(covered)
		.on(covered.parent == regulation.name)
		.join(year)
		.on(year.name == regulation.effective_from_year)
		.select(regulation.name)
		.where(regulation.company == company)
		.where(regulation.status == "Effective")
		.where(covered.program == program)
		.where(year.year_start_date <= batch_start)
		.orderby(year.year_start_date, order=frappe.qb.desc)
		.orderby(regulation.creation, order=frappe.qb.desc)
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None


def get_regulation(student):
	"""Regulation of `student`: the assigned one, else resolved from the latest enrollment."""
	if not frappe.db.exists("Student", student):
		raise frappe.DoesNotExistError(_("Student {0} does not exist.").format(frappe.bold(student)))
	assigned, company, batch = frappe.db.get_value(
		"Student", student, ["oc_regulation", "oc_company", "oc_batch"]
	)
	if assigned:
		return assigned
	enrollment = latest_enrollment(student)
	if enrollment:
		return resolve_regulation(company, enrollment.program, batch or enrollment.academic_year)


def latest_enrollment(student):
	return frappe.db.get_value(
		"Program Enrollment",
		{"student": student, "docstatus": ["<", 2]},
		["program", "academic_year", "name"],
		order_by="enrollment_date desc, creation desc",
		as_dict=True,
	)


def get_rule(student, rule_doctype, **filters):
	"""The `rule_doctype` record linked (field `regulation`) to the student's regulation."""
	regulation = get_regulation(student)
	if not regulation:
		frappe.throw(_("Student {0} has no regulation.").format(frappe.bold(student)))
	if not frappe.get_meta(rule_doctype).has_field("regulation"):
		frappe.throw(_("{0} is not a regulation rule set.").format(_(rule_doctype)))
	names = frappe.get_all(rule_doctype, filters={**filters, "regulation": regulation}, pluck="name", limit=2)
	if not names:
		frappe.throw(
			_("No {0} defined for regulation {1}.").format(_(rule_doctype), frappe.bold(regulation))
		)
	if len(names) > 1:
		frappe.throw(
			_("More than one {0} for regulation {1}; pass filters to pick one.").format(
				_(rule_doctype), frappe.bold(regulation)
			)
		)
	return frappe.get_doc(rule_doctype, names[0])


def assign_regulation_on_enrollment(doc, method=None):
	"""Program Enrollment hook: set the student's batch and regulation when not already set."""
	batch, regulation = frappe.db.get_value("Student", doc.student, ["oc_batch", "oc_regulation"])
	updates = {}
	if not batch:
		batch = updates["oc_batch"] = doc.academic_year
	if not regulation:
		regulation = resolve_regulation(doc.oc_company, doc.program, batch)
		if regulation:
			updates["oc_regulation"] = regulation
	if updates:
		frappe.db.set_value("Student", doc.student, updates)


def validate_regulation_change(doc, method=None):
	"""Student hook: once assigned, oc_regulation moves only through `change_regulation`."""
	before = doc.get_doc_before_save()
	if before and before.oc_regulation and doc.oc_regulation != before.oc_regulation:
		if not doc.flags.in_change_regulation:
			frappe.throw(
				_("Regulation can only be changed by the Dean Academics using Change Regulation."),
				title=_("Regulation Locked"),
			)


@frappe.whitelist()
def change_regulation(student, to_regulation, reason, bridge_courses=None):
	"""Move `student` to `to_regulation` (e.g. rejoin after a break) and log it. Dean Academics only."""
	frappe.only_for(DEAN_ROLE)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to change the regulation."))
	doc = frappe.get_doc("Student", student)
	frappe.has_permission("Student", "read", doc=doc, throw=True)
	regulation = frappe.db.get_value("Regulation", to_regulation, ["company", "status"], as_dict=True)
	if not regulation or regulation.status != "Effective":
		frappe.throw(_("Regulation {0} is not Effective.").format(frappe.bold(to_regulation)))
	if regulation.company != doc.oc_company:
		frappe.throw(_("Regulation {0} belongs to another company.").format(frappe.bold(to_regulation)))
	validate_covers_enrolled_program(doc.name, to_regulation)
	if doc.oc_regulation == to_regulation:
		frappe.throw(_("Student is already on regulation {0}.").format(frappe.bold(to_regulation)))
	doc.append(
		"oc_regulation_history",
		{
			"from_regulation": doc.oc_regulation,
			"to_regulation": to_regulation,
			"change_date": today(),
			"reason": reason,
			"bridge_courses_note": bridge_courses,
		},
	)
	doc.oc_regulation = to_regulation
	doc.flags.in_change_regulation = True
	doc.save(ignore_permissions=True)
	return doc.oc_regulation


def validate_covers_enrolled_program(student, regulation):
	enrollment = latest_enrollment(student)
	if enrollment and not frappe.db.exists(
		"Regulation Program", {"parent": regulation, "program": enrollment.program}
	):
		frappe.throw(
			_("Regulation {0} does not cover the student's program {1}.").format(
				frappe.bold(regulation), frappe.bold(enrollment.program)
			)
		)
