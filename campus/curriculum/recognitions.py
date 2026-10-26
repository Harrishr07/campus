"""M03-09 (thin cut for M05-15) Credit Recognition rules: what a recognition must carry before it is approved, and
its seeded approval policy.

A recognition clears a course of the student's Effective curriculum, so it is approved through the approval engine
(raised by the COE or a Dean, approved by a Dean Academics of the student's college who is neither the requester nor
the owner) and Credit Recognition is on the mandatory approval list. Every kind needs private evidence; every kind but
Waiver needs the credits granted. It is raised only for a college the user may work in, and cannot be cancelled once
the student has completed (Study Completed or later): the completion would no longer hold.
"""

import posixpath

import frappe
from frappe import _
from frappe.utils import flt

from campus.campus_platform.api import get_regulation, permitted_companies
from campus.curriculum.effective import effective_curriculum

DOCTYPE = "Credit Recognition"
POLICY = "Credit Recognition Approval"
WAIVER = "Waiver"
COMPLETED = ("Study Completed", "Award Eligible", "Graduated", "Alumni")  # lifecycle statuses past completion


def seed_recognition_policy():
	"""A Dean Academics of the student's college approves, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": DOCTYPE}):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": POLICY, "document_type": DOCTYPE,
			"levels": [{"title": "Dean Academics", "approver_type": "Role", "approver": "Dean Academics", "limit_to_company": 1, "sla_hours": 72}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def check_recognition(doc):
	"""Throw unless `doc` names a college the user works in, a course of the student's curriculum, private evidence
	and (but for a waiver) the credits granted."""
	doc.company = frappe.db.get_value("Student", doc.student, "oc_company")
	permitted = permitted_companies(frappe.session.user)
	if permitted is not None and doc.company not in permitted:
		frappe.throw(
			_("You cannot record credit recognitions for {0}.").format(doc.company), frappe.PermissionError
		)
	if doc.kind != WAIVER and flt(doc.credits) <= 0:
		frappe.throw(
			_("Enter the credits granted for a {0}; only a waiver may grant none.").format(_(doc.kind))
		)
	if not doc.evidence or not posixpath.normpath(doc.evidence).startswith("/private/files/"):
		frappe.throw(_("Attach the evidence as a private file."))
	if doc.course not in curriculum_courses(doc.student):
		frappe.throw(
			_("{0} is not a course of the student's Effective curriculum.").format(frappe.bold(doc.course))
		)


def curriculum_courses(student):
	"""Courses of the Effective curriculum of the student's programme (latest submitted enrollment), regulation and batch."""
	program = frappe.db.get_value(
		"Program Enrollment",
		{"student": student, "docstatus": 1},
		"program",
		order_by="enrollment_date desc, creation desc",
	)
	regulation = get_regulation(student)
	batch = frappe.db.get_value("Student", student, "oc_batch")
	curriculum = program and regulation and effective_curriculum(program, regulation, batch)
	if not curriculum:
		return set()
	return set(
		frappe.get_all(
			"Curriculum Course", {"parenttype": "Curriculum", "parent": curriculum}, pluck="course"
		)
	)


def check_cancel(doc):
	status = frappe.db.get_value("Student", doc.student, "oc_academic_status")
	if status in COMPLETED:
		frappe.throw(
			_("{0} is {1}: a recognition counted in the completion can no longer be cancelled.").format(
				doc.student, _(status)
			)
		)
