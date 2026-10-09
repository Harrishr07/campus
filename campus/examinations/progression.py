"""M05-03 Progression Run (term end): each Active student of the programme enrolled in the term's year, less those on
a break of study, is promoted, detained or promoted on probation by the Progression Rule of their regulation, from
the outstanding arrears and CGPA of their published results (campus.examinations.graduation).

Bulk: one item per student through campus_platform.bulk.run_bulk. The handler is DB-only and idempotent: a student's
outcome row is written once per run and updated on a re-run, and the semester moves from the row's from_semester,
so re-running never promotes twice. Promote and Probation set the next semester (status Active); Detain sets the
academic status Detained and keeps the semester.
"""

import frappe
from frappe import _
from frappe.utils import cint

from campus.campus_platform.api import get_rule
from campus.examinations import graduation_rules
from campus.examinations.access import COE_ROLE
from campus.examinations.graduation import graduate_record
from campus.examinations.results import program_students

RUN_TYPE = "Progression Run"
HANDLER = "campus.examinations.progression.progress_student"
ROW = "Progression Run Student"
ACTIVE, DETAINED = "Active", "Detained"


def start(run_doc):
	"""Queue the bulk progression of `run_doc` (a submitted Progression Run); returns the Bulk Run name."""
	from campus.campus_platform.bulk import run_bulk

	frappe.only_for((COE_ROLE, "System Manager"))
	return run_bulk(RUN_TYPE, active_students(run_doc), HANDLER, chunk=50, parameters={"progression_run": run_doc.name})


def rerun(progression_run):
	"""Queue a submitted Progression Run again (students added since, a corrected rule); returns the Bulk Run."""
	doc = frappe.get_doc(RUN_TYPE, progression_run)
	doc.check_permission("submit")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the Progression Run first."))
	name = start(doc)
	doc.db_set("bulk_run", name)
	return name


def active_students(run_doc):
	students = program_students(frappe._dict(academic_term=run_doc.academic_term, company=run_doc.company), run_doc.program)
	statuses = dict(frappe.get_all("Student", {"name": ["in", students or [""]]}, ["name", "oc_academic_status"], as_list=True))
	return [s for s in students if (statuses.get(s) or ACTIVE) == ACTIVE]


def progress_student(student, run):
	"""Bulk handler: decide and apply one student's progression; returns the outcome."""
	run_name = run.get_parameters()["progression_run"]
	rule = get_rule(student, "Progression Rule")
	record = graduate_record(student)
	outcome = graduation_rules.progression_outcome(
		len(record.arrears), record.cgpa, cint(rule.max_arrears), rule.probation_below_cgpa
	)
	existing = frappe.db.get_value(ROW, {"parent": run_name, "parenttype": RUN_TYPE, "student": student}, ["name", "from_semester"], as_dict=True)
	from_semester = existing.from_semester if existing else cint(frappe.db.get_value("Student", student, "oc_current_semester"))
	values = {
		"student_name": record.student_name, "from_semester": from_semester, "cgpa": record.cgpa,
		"arrear_count": len(record.arrears), "outcome": outcome,
	}  # fmt: skip
	if existing:
		frappe.db.set_value(ROW, existing.name, values)
	else:
		frappe.get_doc(
			{"doctype": ROW, "parent": run_name, "parenttype": RUN_TYPE, "parentfield": "students", "student": student,
			"idx": frappe.db.count(ROW, {"parent": run_name, "parenttype": RUN_TYPE}) + 1, **values}
		).db_insert()  # fmt: skip
	if outcome == graduation_rules.DETAIN:
		frappe.db.set_value("Student", student, {"oc_academic_status": DETAINED, "oc_current_semester": from_semester})
	else:
		frappe.db.set_value("Student", student, {"oc_academic_status": ACTIVE, "oc_current_semester": from_semester + 1})
	return outcome
