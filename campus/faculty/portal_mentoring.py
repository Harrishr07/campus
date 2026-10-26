"""M05-13 Mentoring on the faculty portal (L-09): on /campus-portal/faculty/mentees?student=<id> the mentor reads
the counselling notes and parent interactions they may read about their own mentee and adds new ones. Records are
read with frappe.get_list and written through the controllers, under the caller's own permissions; the student must
be the caller's current mentee (Student.oc_mentor).
"""

import frappe
from frappe import _
from frappe.utils import cint

from campus.examinations.api import mentees_of
from campus.faculty.portal import require_faculty

NOTE, INTERACTION = "Counselling Note", "Parent Interaction"
NOTE_FIELDS = ["name", "note_date", "category", "notes", "is_confidential", "author", "follow_up_date"]
INTERACTION_FIELDS = [
	"name",
	"interaction_date",
	"guardian_name",
	"mode",
	"outcome",
	"follow_up_due",
	"follow_up_done",
]


def own_mentee(student):
	require_faculty()
	if not student or student not in mentees_of(frappe.session.user):
		frappe.throw(_("This student is not your mentee."), frappe.PermissionError)


@frappe.whitelist()
def mentee_record(student):
	"""The mentee, their guardians, and the notes and interactions the caller may read (newest first)."""
	own_mentee(student)
	return {
		"student": student,
		"student_name": frappe.db.get_value("Student", student, "student_name"),
		"guardians": frappe.get_all(
			"Student Guardian",
			{"parent": student, "parenttype": "Student"},
			["guardian", "guardian_name", "relation"],
			order_by="idx",
		),
		"notes": frappe.get_list(
			NOTE, {"student": student}, NOTE_FIELDS, order_by="note_date desc, creation desc"
		),
		"interactions": frappe.get_list(
			INTERACTION,
			{"student": student},
			INTERACTION_FIELDS,
			order_by="interaction_date desc, creation desc",
		),
		"categories": options(NOTE, "category"),
		"modes": options(INTERACTION, "mode"),
	}


@frappe.whitelist(methods=["POST"])
def add_note(
	student,
	category,
	notes,
	note_date=None,
	follow_up_date=None,
	is_confidential=0,
	action=None,
	action_due=None,
):
	"""A Counselling Note by the caller; an agreed action given here is the caller's own."""
	own_mentee(student)
	actions = (
		[{"action": action, "action_owner": frappe.session.user, "due_date": action_due or None}]
		if action
		else []
	)
	doc = frappe.get_doc(
		{
			"doctype": NOTE, "student": student, "category": category, "notes": notes, "note_date": note_date or None,
			"follow_up_date": follow_up_date or None, "is_confidential": cint(is_confidential), "actions": actions,
		}
	)  # fmt: skip
	return doc.insert().name


@frappe.whitelist(methods=["POST"])
def add_parent_interaction(student, guardian, mode, outcome, interaction_date=None, follow_up_due=None):
	"""A Parent Interaction by the caller; a follow-up due date makes the caller its owner."""
	own_mentee(student)
	doc = frappe.get_doc(
		{
			"doctype": INTERACTION, "student": student, "guardian": guardian, "mode": mode, "outcome": outcome,
			"interaction_date": interaction_date or None, "follow_up_due": follow_up_due or None,
			"follow_up_owner": frappe.session.user if follow_up_due else None,
		}
	)  # fmt: skip
	return doc.insert().name


def options(doctype, fieldname):
	return [o for o in (frappe.get_meta(doctype).get_options(fieldname) or "").split("\n") if o]
