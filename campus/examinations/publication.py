"""M06-06 Result publication: Passing Board approval, the release time and the release notice.

`publish_results` (COE) publishes an Exam Session on the approving resolution of a quorate, uncancelled meeting of
a Passing Board of the session's company (Body Meeting, P2-T02); one resolution publishes one session. The session
becomes Published with publish_at = the release time: until then the permission query (campus.examinations.access)
keeps results from students, guardians and staff other than the COE, System Manager and Dean Academics, on the
API and the portal alike. The scheduler (`notify_released_results`, every 15 minutes) queues, once per session and
at release, a bulk run that sends each latest Student Result to the student and guardians through messaging send()
(SMS / WhatsApp / email by the template and the recipient's consent).
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from campus.campus_messaging.api import send
from campus.campus_platform.bulk import run_bulk
from campus.examinations.access import MARKS_ROLES

PASSING_BOARD = "Passing Board"
RESULT, SESSION = "Student Result", "Exam Session"
RELEASE_EVENT = "exam.result_published"
RUN_TYPE = "Result Release Notice"
HANDLER = "campus.examinations.publication.notify_result"
RELEASE_TEMPLATE = (
	"Results published: {{ doc.exam_session }}",
	"The results of {{ doc.student_name }} for {{ doc.exam_session }} are published: SGPA {{ doc.sgpa }}, CGPA "
	"{{ doc.cgpa }}, result {{ doc.result }}. The grades are on the campus portal.",
)


@frappe.whitelist(methods=["POST"])
def publish_results(exam_session, release_at, passing_board_meeting, resolution_no):
	"""COE: publish the session's results at `release_at` on Passing Board resolution `resolution_no`."""
	frappe.only_for(MARKS_ROLES)
	frappe.db.get_value(SESSION, exam_session, "name", for_update=True)  # one publication at a time
	session = frappe.get_doc(SESSION, exam_session)
	session.check_permission("write")
	if session.status == "Published":
		frappe.throw(_("{0} is already published.").format(frappe.bold(exam_session)))
	if not frappe.db.exists(RESULT, {"exam_session": exam_session}):
		frappe.throw(_("Run the results of {0} before publishing them.").format(frappe.bold(exam_session)))
	check_resolution(session, passing_board_meeting, resolution_no)
	session.update(
		{"status": "Published", "publish_at": get_datetime(release_at), "passing_board_meeting": passing_board_meeting,
		"passing_board_resolution": resolution_no}
	)  # fmt: skip
	session.flags.passing_board_approval = True
	session.save()
	return session.name


def check_resolution(session, meeting_name, resolution_no):
	"""Refuse unless `resolution_no` approves, in a quorate meeting of the company's Passing Board, and has not
	published another session."""
	meeting = frappe.db.get_value("Body Meeting", meeting_name, ["body", "company", "status", "quorum_status", "docstatus"], as_dict=True)
	if not meeting:
		frappe.throw(_("Body Meeting {0} does not exist.").format(frappe.bold(meeting_name)))
	if frappe.db.get_value("Body", meeting.body, "body_type") != PASSING_BOARD:
		frappe.throw(_("{0} is not a meeting of a Passing Board.").format(frappe.bold(meeting_name)))
	if meeting.company != session.company:
		frappe.throw(_("{0} is a meeting of another college.").format(frappe.bold(meeting_name)))
	if meeting.status == "Cancelled" or meeting.docstatus == 2 or meeting.quorum_status != "Met":
		frappe.throw(_("{0} was cancelled or did not meet quorum.").format(frappe.bold(meeting_name)))
	decision = frappe.db.get_value(
		"Meeting Resolution", {"parent": meeting_name, "parenttype": "Body Meeting", "resolution_no": resolution_no, "void": 0}, "decision"
	)
	if not decision:
		frappe.throw(_("{0} has no resolution {1}.").format(frappe.bold(meeting_name), frappe.bold(resolution_no)))
	if decision != "Approved":
		frappe.throw(_("Resolution {0} does not approve the results (decision: {1}).").format(frappe.bold(resolution_no), _(decision)))
	used = frappe.db.get_value(
		SESSION, {"passing_board_meeting": meeting_name, "passing_board_resolution": resolution_no, "name": ["!=", session.name]}
	)
	if used:
		frappe.throw(_("Resolution {0} already published {1}.").format(frappe.bold(resolution_no), frappe.bold(used)))


def notify_released_results():
	"""Scheduler: queue the release notice of every session published through a Passing Board whose release time
	has come and whose notice is not queued yet."""
	due = frappe.get_all(
		SESSION,
		{"status": "Published", "publish_at": ["<=", now_datetime()], "passing_board_meeting": ["is", "set"], "results_notified_on": ["is", "not set"]},
		pluck="name",
	)
	for name in due:
		if frappe.db.get_value(SESSION, name, "results_notified_on", for_update=True):
			continue
		frappe.db.set_value(SESSION, name, "results_notified_on", now_datetime(), update_modified=False)
		names = frappe.get_all(RESULT, {"exam_session": name, "is_latest": 1}, pluck="name", order_by="name")
		if names:
			run_bulk(RUN_TYPE, names, HANDLER, parameters={"exam_session": name})


def notify_result(name, run):
	"""Bulk handler: send one latest Student Result's release notice to the student and the guardians."""
	doc = frappe.get_doc(RESULT, name)
	if not doc.is_latest:
		return False
	guardians = frappe.get_all("Student Guardian", {"parent": doc.student, "parenttype": "Student"}, pluck="guardian", order_by="idx")
	send(RELEASE_EVENT, doc, [f"Student:{doc.student}", *(f"Guardian:{g}" for g in guardians)])
	return True


def seed_release_template():
	"""The release notice template; an existing (possibly edited) one is left alone."""
	if frappe.db.exists("Message Template", RELEASE_EVENT):
		return
	subject, body = RELEASE_TEMPLATE
	frappe.get_doc(
		{
			"doctype": "Message Template", "event_key": RELEASE_EVENT, "purpose": "transactional",
			"channels": [{"channel": "sms"}, {"channel": "whatsapp"}, {"channel": "email"}],
			"bodies": [{"language": "en", "subject": subject, "body": body}],
		}
	).insert(ignore_permissions=True)  # fmt: skip
