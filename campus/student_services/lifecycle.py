"""M05-09 Student lifecycle service: the one way a Student's lifecycle status (Student.oc_academic_status) changes.

`transition` takes the Student row lock, checks the move against the enabled Lifecycle Transition Rules (the
configurable table, seeded with lifecycle_rules.DEFAULT_TRANSITIONS) and the effective date against the student's
last change, sets the status and writes a Lifecycle Transition (from, to, effective date, reason, source document,
approved by, program enrollment). A retry from the same source returns the earlier record. `revert` undoes a
source's latest transition with a Reversal record, only while it is still the student's latest change.

A new Student starts in a status the table permits from blank (Initial record); saving a Student that changes the
status is refused (validate_student). Flows: admit (Admitted, Joined, Active), Admission Cancellation (Cancelled),
Break of Study (On Break; cancel reverts), Rejoin Application (back to the status before the break), transfer
certificate (Withdrawn when still on roll; cancel reverts), Convocation List (Study Completed, Award Eligible,
Graduated). migrate_students gives students recorded before L-01 their status from their records (Migrated).
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.student_services import lifecycle_rules as rules

LOG, RULE, FIELD = "Lifecycle Transition", "Lifecycle Transition Rule", "oc_academic_status"
TRANSITION, INITIAL, MIGRATED, REVERSAL = "Transition", "Initial", "Migrated", "Reversal"
NEW_RECORD = "New Record"  # the rule name part for a blank From Status


def rule_name(from_status, to_status):
	return f"{from_status or NEW_RECORD} to {to_status}"


def transition(student, to_status, effective_date=None, reason=None, source=None, approved_by=None, program_enrollment=None):
	"""Move `student` to `to_status` from `effective_date` (default today); returns the Lifecycle Transition name.

	`source` is the document causing the change (a Document or (doctype, name)). `approved_by` defaults to the
	session user, `program_enrollment` to the student's latest submitted one. Throws when the table does not
	permit the move or the date is before the student's last change."""
	source_doctype, source_name = source_ref(source)
	current = lock_student(student)
	latest = latest_transition(student)
	if latest and source_name and (latest.source_doctype, latest.source_name, latest.to_status) == (source_doctype, source_name, to_status):
		if current.status == to_status:
			return latest.name  # a retry of the same change
	effective = getdate(effective_date or today())
	check(student, current.status, to_status, effective, latest)
	return write(
		student, current, to_status, effective, TRANSITION, reason, (source_doctype, source_name),
		approved_by or frappe.session.user, program_enrollment,
	)  # fmt: skip


def revert(source, reason):
	"""Undo the latest live transition made by `source` (a Reversal record back to its From status); returns the
	Reversal name, or None when the source made no transition. Throws when the student has changed since."""
	source_doctype, source_name = source_ref(source)
	original = live_transition_of(source_doctype, source_name)
	if not original:
		return None
	current = lock_student(original.student)
	latest = latest_transition(original.student)
	if not latest or latest.name != original.name or current.status != original.to_status:
		frappe.throw(
			_("{0} {1} cannot be undone: the lifecycle status of {2} has changed since ({3}).").format(
				_(source_doctype), source_name, frappe.bold(original.student), current.status
			)
		)
	return write(
		original.student, current, original.from_status, original.effective_date, REVERSAL, reason,
		(source_doctype, source_name), frappe.session.user, original.program_enrollment, reverses=original.name,
	)  # fmt: skip


def current_status(student):
	return frappe.db.get_value("Student", student, FIELD)


def check(student, from_status, to_status, effective, latest):
	problem = rules.refusal(permitted_moves(), from_status, to_status, effective, latest and latest.effective_date)
	if problem == rules.UNKNOWN_STATUS:
		frappe.throw(_("{0} is not a lifecycle status.").format(frappe.bold(to_status)))
	if problem == rules.SAME_STATUS:
		frappe.throw(_("{0} is already {1}.").format(frappe.bold(student), _(to_status)))
	if problem == rules.NOT_PERMITTED:
		frappe.throw(
			_("{0} cannot move from {1} to {2}: no enabled Lifecycle Transition Rule permits it.").format(
				frappe.bold(student), from_status or _("a new record"), to_status
			)
		)
	if problem == rules.BEFORE_LATEST:
		frappe.throw(
			_("The effective date {0} is before the last status change of {1} ({2} from {3}).").format(
				frappe.format(effective, "Date"), frappe.bold(student), latest.to_status, frappe.format(latest.effective_date, "Date")
			)
		)


def permitted_moves():
	return {(row.from_status or rules.NEW, row.to_status) for row in frappe.get_all(RULE, {"enabled": 1}, ["from_status", "to_status"])}


def lock_student(student):
	"""The Student row lock (one status change at a time) with the status and company read under it."""
	row = frappe.db.get_value("Student", student, [FIELD, "oc_company"], as_dict=True, for_update=True)
	if not row:
		raise frappe.DoesNotExistError(_("Student {0} does not exist.").format(student))
	return frappe._dict(status=row.get(FIELD), company=row.oc_company)


def latest_transition(student):
	"""The student's last Lifecycle Transition, read with a locking read (taken after the Student lock)."""
	log = frappe.qb.DocType(LOG)
	rows = (
		frappe.qb.from_(log)
		.select(log.name, log.to_status, log.effective_date, log.source_doctype, log.source_name)
		.where(log.student == student)
		.orderby(log.creation, order=frappe.qb.desc)
		.orderby(log.name, order=frappe.qb.desc)
		.limit(1)
		.for_update()
		.run(as_dict=True)
	)
	return rows[0] if rows else None


def live_transition_of(source_doctype, source_name):
	"""The latest non-reversal transition made by the source that no Reversal undoes yet."""
	reversed_names = frappe.get_all(LOG, {"kind": REVERSAL, "source_doctype": source_doctype, "source_name": source_name}, pluck="reverses")
	rows = frappe.get_all(
		LOG,
		{"kind": ["!=", REVERSAL], "source_doctype": source_doctype, "source_name": source_name, "name": ["not in", reversed_names or [""]]},
		["name", "student", "from_status", "to_status", "effective_date", "program_enrollment"],
		order_by="creation desc, name desc",
		limit=1,
	)
	return rows[0] if rows else None


def write(student, current, to_status, effective, kind, reason, source, approved_by, program_enrollment, reverses=None):
	frappe.db.set_value("Student", student, FIELD, to_status)
	return insert_log(
		student, current.company, current.status, to_status, effective, kind, reason, source, approved_by,
		program_enrollment or latest_enrollment(student), reverses,
	).name  # fmt: skip


def insert_log(student, company, from_status, to_status, effective, kind, reason, source, approved_by, program_enrollment, reverses=None):
	doc = frappe.get_doc(
		{
			"doctype": LOG, "student": student, "company": company, "from_status": from_status or rules.NEW,
			"to_status": to_status, "effective_date": effective, "kind": kind, "reason": reason,
			"source_doctype": source[0], "source_name": source[1], "approved_by": approved_by,
			"program_enrollment": program_enrollment, "reverses": reverses,
		}
	)  # fmt: skip
	doc.flags.from_lifecycle_service = True
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True  # a cancelled enrollment or source stays the record's reference
	return doc.insert()


def latest_enrollment(student):
	return frappe.db.get_value(
		"Program Enrollment", {"student": student, "docstatus": 1}, "name", order_by="enrollment_date desc, creation desc"
	)


def source_ref(source):
	if source is None:
		return None, None
	if isinstance(source, (tuple, list)):
		return source[0], source[1]
	return source.doctype, source.name


# Student hooks


def validate_student(doc, method=None):
	"""A new Student starts in a status the table permits from blank; afterwards a save never changes it."""
	if doc.is_new():
		doc.set(FIELD, doc.get(FIELD) or rules.ACTIVE)
		problem = rules.refusal(permitted_moves(), rules.NEW, doc.get(FIELD), None, None)
		if problem:
			frappe.throw(
				_("A new student cannot start as {0}: no enabled Lifecycle Transition Rule permits it.").format(_(doc.get(FIELD)))
			)
	elif doc.has_value_changed(FIELD):
		frappe.throw(
			_("The lifecycle status changes only through a lifecycle transition (admission, break, rejoin, cancellation, TC, convocation), not by editing the Student.")
		)


def log_initial_status(doc, method=None):
	"""The Initial record of a new Student, dated from the start of its record; the source is its applicant."""
	source = ("Student Applicant", doc.student_applicant) if doc.get("student_applicant") else (None, None)
	insert_log(
		doc.name, doc.get("oc_company"), rules.NEW, doc.get(FIELD), start_date(doc.joining_date, doc.get("oc_batch")),
		INITIAL, _("New student record"), source, frappe.session.user, None,
	)  # fmt: skip


def start_date(joining_date, batch, fallback=None):
	"""When the student's record starts: the earlier of the joining date (Education defaults it to the day the
	record is made) and the start of the batch (admission year); else `fallback`, else today."""
	batch_start = batch and frappe.db.get_value("Academic Year", batch, "year_start_date")
	dates = [getdate(d) for d in (joining_date, batch_start) if d]
	return min(dates) if dates else getdate(fallback or today())


# Migration of students recorded before L-01 (patch student_lifecycle_status)


def migrate_students():
	"""Give every student without a Lifecycle Transition its status from its records (one Migrated record each)."""
	recorded = set(frappe.get_all(LOG, pluck="student", distinct=True))
	for student in frappe.get_all("Student", pluck="name", order_by="creation asc"):
		if student not in recorded:
			migrate_student(student)


def migrate_student(student):
	"""Derive and record the lifecycle status of a student recorded before L-01; returns the status."""
	current = lock_student(student)
	facts = legacy_facts(student)
	status = rules.migrated_status(
		current.status, cancelled=bool(facts.cancellation), left=bool(facts.leaving_certificate_number),
		open_break=bool(facts.open_break), convocation=bool(facts.convocation),
	)  # fmt: skip
	source, effective, evidence = migration_evidence(status, facts)
	frappe.db.set_value(
		"Student", student, {FIELD: status, "oc_detained": int(current.status == rules.LEGACY_DETAINED)}, update_modified=False
	)
	reason = _("Migrated from the academic status {0}").format(current.status or _("(blank)"))
	insert_log(
		student, current.company, current.status, status, effective, MIGRATED, f"{reason}{evidence}", source,
		frappe.session.user, latest_enrollment(student),
	)  # fmt: skip
	return status


def legacy_facts(student):
	row = frappe.db.get_value("Student", student, ["joining_date", "oc_batch", "creation", "leaving_certificate_number", "date_of_leaving"], as_dict=True)
	row.cancellation = frappe.db.get_value(
		"Admission Cancellation", {"student": student, "docstatus": 1}, ["name", "cancellation_date"], as_dict=True
	)
	row.tc = row.leaving_certificate_number and frappe.db.get_value(
		"Certificate Request", {"student": student, "certificate_number": row.leaving_certificate_number, "docstatus": 1}, "name"
	)
	row.open_break = open_break(student)
	row.convocation = frappe.db.get_value("Convocation List Graduate", {"student": student, "parenttype": "Convocation List"}, "parent")
	return row


def open_break(student):
	"""The student's approved Break of Study with no approved rejoin, or None."""
	if not frappe.db.table_exists("Break of Study"):
		return None
	rejoined = frappe.get_all("Rejoin Application", {"student": student, "docstatus": 1}, pluck="break_of_study")
	return frappe.db.get_value(
		"Break of Study", {"student": student, "docstatus": 1, "name": ["not in", rejoined or [""]]}, ["name", "from_date"], as_dict=True
	)


def migration_evidence(status, facts):
	"""(source, effective date, reason suffix) of a migrated status from the record that shows it."""
	started = start_date(facts.joining_date, facts.oc_batch, facts.creation)
	if status == rules.CANCELLED:
		return ("Admission Cancellation", facts.cancellation.name), getdate(facts.cancellation.cancellation_date), ""
	if status == rules.AWARD_ELIGIBLE:
		return ("Convocation List", facts.convocation), getdate(today()), ""
	if status == rules.WITHDRAWN:
		return ("Certificate Request", facts.tc), getdate(facts.date_of_leaving or started), _(" (transfer certificate {0})").format(
			facts.leaving_certificate_number
		)
	if status == rules.ON_BREAK and facts.open_break:
		return ("Break of Study", facts.open_break.name), getdate(facts.open_break.from_date), ""
	return (None, None), started, ""
