"""M05-12 Class session states on a Course Schedule: Scheduled, Conducted, Cancelled, Rescheduled (to the new session),
Makeup (for the session it replaces). How each state counts is campus.student_services.attendance_rules.

Changing the state of a session whose attendance is marked needs a new reason, and the change is logged as a comment
on the session. Marking attendance makes a Scheduled session Conducted; a Cancelled or Rescheduled one cannot be marked.
"""

import frappe
from frappe import _

from campus.student_services.attendance_rules import CANCELLED, CONDUCTED, MAKEUP, RESCHEDULED, SCHEDULED

NOT_HELD = (CANCELLED, RESCHEDULED)
LINKS = {RESCHEDULED: "oc_rescheduled_to", MAKEUP: "oc_makeup_for"}


def validate_session(doc, method=None):
	"""Course Schedule validate: the state's link is set (to another session of the group) and the others cleared; a
	change after marking needs a new reason."""
	doc.oc_session_state = doc.oc_session_state or SCHEDULED
	for state, fieldname in LINKS.items():
		if doc.oc_session_state != state:
			doc.set(fieldname, None)
		else:
			check_link(doc, fieldname)
	if doc.is_new() or not doc.has_value_changed("oc_session_state") or not is_marked(doc.name):
		return
	if not (doc.oc_state_reason or "").strip() or not doc.has_value_changed("oc_state_reason"):
		frappe.throw(_("Attendance is marked for {0}: give the reason for changing its state.").format(doc.name))
	doc.flags.log_state_change = True


def check_link(doc, fieldname):
	label = _(doc.meta.get_label(fieldname))
	other = doc.get(fieldname)
	if not other:
		frappe.throw(_("{0} is needed for a {1} session.").format(label, _(doc.oc_session_state)))
	if other == doc.name or frappe.db.get_value("Course Schedule", other, "student_group") != doc.student_group:
		frappe.throw(_("{0} must be another session of {1}.").format(label, doc.student_group))


def log_state_change(doc, method=None):
	"""Course Schedule on_update: the comment recording a state change after marking."""
	if not doc.flags.log_state_change:
		return
	doc.flags.log_state_change = False
	before = doc.get_doc_before_save()
	doc.add_comment(
		"Info",
		_("Session state changed from {0} to {1}: {2}").format(
			_(before.oc_session_state or SCHEDULED), _(doc.oc_session_state), doc.oc_state_reason.strip()
		),
	)


def is_marked(course_schedule):
	return bool(frappe.db.exists("Student Attendance", {"course_schedule": course_schedule, "docstatus": 1}))


def check_markable(course_schedule, state):
	"""Refuse marking a session that was not held."""
	if state in NOT_HELD:
		frappe.throw(_("{0} is {1}; its attendance cannot be marked.").format(course_schedule, _(state)))


def mark_conducted(course_schedule, state):
	"""Marking a Scheduled (or blank) session makes it Conducted."""
	if (state or SCHEDULED) == SCHEDULED:
		frappe.db.set_value("Course Schedule", course_schedule, "oc_session_state", CONDUCTED)
