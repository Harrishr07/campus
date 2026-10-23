"""M05-13 Mentoring (L-09): the roles and reminder template the mentoring records use, and the daily follow-up
reminders for Counselling Notes (their follow-up date and open agreed actions) and Parent Interactions (open
follow-ups). A reminder names the record and the student, never the note text: `send` gets a stand-in doc that
carries nothing else, so no template edit can print the notes. Who reads what: campus.student_services.mentoring_access.
"""

import frappe
from frappe.utils import add_days, getdate, today

from campus.campus_messaging.api import send

NOTE, NOTE_ACTION, INTERACTION = "Counselling Note", "Counselling Note Action", "Parent Interaction"
MENTOR_ROLE, COUNSELLOR_ROLE, CLASS_ADVISOR_ROLE = "Mentor", "Student Counsellor", "Class Advisor"
HOD_ROLE, PRINCIPAL_ROLE = "HOD", "Principal"
# Office roles see every Parent Interaction of their companies (User Permissions still apply).
OFFICE_ROLES = (PRINCIPAL_ROLE, "Dean Student Affairs", "System Manager")
MENTORING_ROLES = (MENTOR_ROLE, COUNSELLOR_ROLE, CLASS_ADVISOR_ROLE, HOD_ROLE, *OFFICE_ROLES)
FOLLOW_UP_EVENT = "mentoring.follow_up"
LOOKBACK_DAYS = 7  # a follow-up missed while the scheduler was down is still reminded within a week


def setup_mentoring():
	ensure_mentoring_roles()
	seed_follow_up_template()


def ensure_mentoring_roles():
	"""The roles the mentoring DocTypes' permissions name; they must exist before the DocTypes sync."""
	for role in MENTORING_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def seed_follow_up_template():
	if frappe.db.exists("Message Template", FOLLOW_UP_EVENT):
		return
	frappe.get_doc(
		{
			"doctype": "Message Template", "event_key": FOLLOW_UP_EVENT, "purpose": "transactional",
			"channels": [{"channel": "email"}, {"channel": "whatsapp"}],
			"bodies": [
				{
					"language": "en",
					"subject": "Mentoring follow-up due: {{ doc.student_name }}",
					"body": "A mentoring {{ context.kind }} for {{ doc.student_name }} ({{ doc.doctype }} {{ doc.name }}) is due on "
					"{{ frappe.format(context.due_date, {'fieldtype': 'Date'}) }}.",
				}
			],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def student_department(student):
	"""The department of the programme of the student's latest submitted enrollment."""
	program = frappe.db.get_value("Program Enrollment", {"student": student, "docstatus": 1}, "program", order_by="enrollment_date desc")
	return program and frappe.db.get_value("Program", program, "department")


# ---- reminders ------------------------------------------------------------------------------


def send_follow_up_reminders(on_date=None):
	"""Scheduler entry point (daily). Each follow-up is reminded once per due date (send() dedupes the token)."""
	on_date = getdate(on_date or today())
	window = ["between", [add_days(on_date, -LOOKBACK_DAYS), on_date]]
	due = [*note_follow_ups(window), *action_follow_ups(window), *interaction_follow_ups(window)]
	for item in due:
		remind(item)
	return len(due)


def note_follow_ups(window):
	rows = frappe.get_all(NOTE, {"follow_up_date": window}, ["name", "student_name", "author", "follow_up_date"])
	return [reminder(NOTE, r.name, r.student_name, r.author, r.follow_up_date, "follow-up", f"follow-up:{r.follow_up_date}") for r in rows]


def action_follow_ups(window):
	rows = frappe.get_all(NOTE_ACTION, {"parenttype": NOTE, "due_date": window, "done": 0}, ["name", "parent", "action_owner", "due_date"])
	parents = list({r.parent for r in rows}) or [""]
	students = dict(frappe.get_all(NOTE, {"name": ["in", parents]}, ["name", "student_name"], as_list=True))
	return [
		reminder(NOTE, r.parent, students.get(r.parent), r.action_owner, r.due_date, "agreed action", f"action:{r.name}:{r.due_date}")
		for r in rows
	]


def interaction_follow_ups(window):
	rows = frappe.get_all(
		INTERACTION, {"follow_up_due": window, "follow_up_done": 0, "follow_up_owner": ["is", "set"]},
		["name", "student_name", "follow_up_owner", "follow_up_due"],
	)  # fmt: skip
	return [
		reminder(INTERACTION, r.name, r.student_name, r.follow_up_owner, r.follow_up_due, "parent follow-up", f"follow-up:{r.follow_up_due}")
		for r in rows
	]


def reminder(doctype, name, student_name, user, due_date, kind, token):
	return frappe._dict(doctype=doctype, name=name, student_name=student_name, user=user, due_date=due_date, kind=kind, token=token)


def remind(item):
	stand_in = frappe._dict(doctype=item.doctype, name=item.name, student_name=item.student_name)  # never the note text
	context = {"due_date": item.due_date, "kind": item.kind, "dedupe_token": item.token}
	try:
		send(FOLLOW_UP_EVENT, stand_in, [f"User:{item.user}"], context=context)
	except (frappe.ValidationError, frappe.OutgoingEmailError):
		frappe.log_error(title=f"Mentoring follow-up reminder failed for {item.doctype} {item.name}")  # keep the rest going
