"""M06-06 Result publication: Passing Board approval, the release time and the release notice.

`publish_results` (COE) publishes an Exam Session on the approving resolution of a Held, quorate meeting of a Passing
Board of the session's company (Body Meeting, P2-T02). The resolution names the session (Meeting Resolution
exam_session), the meeting sits no earlier than the last Result Run of the session finished, every programme with
results has a finished run and none is in flight, and the publisher is not the one who recorded the meeting; one
resolution publishes one session. Publication freezes the relative bands of each course (frozen_bands), which
every later re-run of the session reuses (campus.examinations.result_cohort). The session
becomes Published with publish_at = the release time: until then the permission query (campus.examinations.access)
keeps results from students, guardians and staff other than the COE, System Manager and Dean Academics, on the
API and the portal alike. The scheduler (`notify_released_results`, every 15 minutes) queues, once per session and
at release, a bulk run that sends each latest Student Result to the student and guardians through messaging send()
(SMS / WhatsApp / email by the template and the recipient's consent).
"""

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from campus.campus_messaging.api import send
from campus.campus_platform.bulk import live_run, run_bulk
from campus.examinations.access import MARKS_ROLES
from campus.examinations.result_cohort import band_key

PASSING_BOARD = "Passing Board"
RESULT, SESSION = "Student Result", "Exam Session"
RELEASE_EVENT = "exam.result_published"
RUN_TYPE = "Result Release Notice"
HANDLER = "campus.examinations.publication.notify_result"
RESULT_RUN = "Result Run"
ENDED = ("Completed", "Completed with errors", "Failed")
INPUTS = ("Student Result", "Mark Sheet Entry", "Mark Moderation")  # all carry exam_session
REVISED_EVENT = "exam.result_revised"
REVISED_TEMPLATE = (
	"Results revised: {{ doc.exam_session }}",
	"The results of {{ doc.student_name }} for {{ doc.exam_session }} are revised: SGPA {{ doc.sgpa }}, CGPA "
	"{{ doc.cgpa }}, result {{ doc.result }}. The grades are on the campus portal.",
)
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
	if not release_at:
		frappe.throw(_("Set the Release At time of the results."))
	if not frappe.db.exists(RESULT, {"exam_session": exam_session}):
		frappe.throw(_("Run the results of {0} before publishing them.").format(frappe.bold(exam_session)))
	finished = check_runs(session)
	meeting_at = check_resolution(session, passing_board_meeting, resolution_no, finished)
	check_inputs(session, finished, meeting_at)
	freeze_bands(exam_session)
	session.update(
		{"status": "Published", "publish_at": get_datetime(release_at), "passing_board_meeting": passing_board_meeting,
		"passing_board_resolution": resolution_no}
	)  # fmt: skip
	session.flags.passing_board_approval = True
	session.save()
	return session.name


def check_runs(session):
	"""When the last Result Run of the session finished. Refused while a run is queued or running, unless every
	programme with results has runs and its latest finished run completed cleanly."""
	if live_run(RESULT_RUN, exam_session=session.name):
		frappe.throw(_("A Result Run of {0} is still running.").format(frappe.bold(session.name)))
	latest = {}
	for status, stored, at in frappe.get_all(
		"Bulk Run", {"run_type": RESULT_RUN, "status": ["in", ENDED]}, ["status", "parameters", "finished_at"], order_by="creation", as_list=True
	):
		params = json.loads(stored or "{}")
		if params.get("exam_session") == session.name:
			latest[params.get("program")] = (status, at)
	programs = set(frappe.get_all(RESULT, {"exam_session": session.name}, pluck="program", distinct=True)) - {None, ""}
	missing = sorted(p for p in programs if p not in latest)
	if missing or not latest:
		frappe.throw(_("Finish a Result Run of {0} for every programme first: {1}.").format(frappe.bold(session.name), ", ".join(missing) or "-"))
	unclean = sorted(p or "-" for p, (status, at) in latest.items() if status != "Completed" or not at)
	if unclean:
		frappe.throw(_("The latest Result Run of {0} did not finish clean (completed without errors); run it again.").format(", ".join(unclean)))
	return max(get_datetime(at) for _status, at in latest.values())


def check_inputs(session, runs_finished, meeting_at):
	"""Refuse when a grading input of the session (its Student Results, Mark Sheet Entries or Mark Moderations)
	changed after the last Result Run finished or after the Passing Board sat: the board approved other results."""
	stamps = [frappe.db.get_value(doctype, {"exam_session": session.name}, "modified", order_by="modified desc") for doctype in INPUTS]
	changed = max((get_datetime(at) for at in stamps if at), default=None)
	if changed and (changed > runs_finished or changed > meeting_at):
		frappe.throw(
			_("Grading inputs of {0} changed on {1}, after the last Result Run or the Passing Board meeting. Run the results again and take a new resolution.").format(
				frappe.bold(session.name), changed
			)
		)


def check_resolution(session, meeting_name, resolution_no, runs_finished):
	"""Refuse unless `resolution_no` names this session and approves it, in a Held, quorate meeting of the company's
	Passing Board after the Result Runs finished, recorded by someone else, and has not published another session."""
	meeting = frappe.db.get_value(
		"Body Meeting", meeting_name,
		["body", "company", "status", "quorum_status", "docstatus", "meeting_date", "start_time", "owner"], as_dict=True,
	)
	if not meeting:
		frappe.throw(_("Body Meeting {0} does not exist.").format(frappe.bold(meeting_name)))
	if frappe.db.get_value("Body", meeting.body, "body_type") != PASSING_BOARD:
		frappe.throw(_("{0} is not a meeting of a Passing Board.").format(frappe.bold(meeting_name)))
	if meeting.company != session.company:
		frappe.throw(_("{0} is a meeting of another college.").format(frappe.bold(meeting_name)))
	if meeting.status != "Held" or meeting.docstatus == 2 or meeting.quorum_status != "Met":
		frappe.throw(_("{0} must be Held with its quorum met.").format(frappe.bold(meeting_name)))
	meeting_at = get_datetime(f"{getdate(meeting.meeting_date)} {meeting.start_time or '00:00:00'}")
	if meeting_at < runs_finished:
		frappe.throw(_("{0} sat before the last Result Run of {1} finished.").format(frappe.bold(meeting_name), frappe.bold(session.name)))
	if meeting.owner == frappe.session.user:
		frappe.throw(_("{0} was recorded by you; another COE user publishes on it.").format(frappe.bold(meeting_name)))
	resolution = frappe.db.get_value(
		"Meeting Resolution", {"parent": meeting_name, "parenttype": "Body Meeting", "resolution_no": resolution_no, "void": 0},
		["decision", "exam_session", "recorded_by"], as_dict=True,
	)  # fmt: skip
	if not resolution:
		frappe.throw(_("{0} has no resolution {1}.").format(frappe.bold(meeting_name), frappe.bold(resolution_no)))
	decision = resolution.decision
	if resolution.recorded_by == frappe.session.user:
		frappe.throw(_("Resolution {0} was recorded by you; another COE user publishes on it.").format(frappe.bold(resolution_no)))
	if resolution.exam_session != session.name:
		frappe.throw(_("Resolution {0} does not name the exam session {1}.").format(frappe.bold(resolution_no), frappe.bold(session.name)))
	if decision != "Approved":
		frappe.throw(_("Resolution {0} does not approve the results (decision: {1}).").format(frappe.bold(resolution_no), _(decision)))
	used = frappe.db.get_value(
		SESSION, {"passing_board_meeting": meeting_name, "passing_board_resolution": resolution_no, "name": ["!=", session.name]}
	)
	if used:
		frappe.throw(_("Resolution {0} already published {1}.").format(frappe.bold(resolution_no), frappe.bold(used)))
	return meeting_at


def freeze_bands(exam_session):
	"""Freeze, and return, the relative bands the session's last Result Run graded on: {band_key: bands}, recorded by
	the run (campus.examinations.result_cohort). A relatively graded course with no recorded bands (results run
	before bands were recorded) gets them from the cohort now; the input guard makes that the run's cohort."""
	from campus.examinations.results import new_cohorts

	frozen = json.loads(frappe.db.get_value(SESSION, exam_session, "frozen_bands") or "{}")
	result, row = frappe.qb.DocType(RESULT), frappe.qb.DocType("Student Result Course")
	pairs = (
		frappe.qb.from_(result)
		.join(row)
		.on((row.parent == result.name) & (row.parenttype == RESULT))
		.select(row.course, result.regulation)
		.distinct()
		.where((result.exam_session == exam_session) & (result.is_latest == 1) & (row.grading_method == "Relative Box-Cox"))
		.run()
	)
	cohorts = None
	for course, regulation in pairs:
		scheme = frappe.get_doc("Grading Scheme", {"regulation": regulation})
		if band_key(course, scheme.name) not in frozen:
			cohorts = cohorts or new_cohorts(exam_session, frozen=False)
			frozen[band_key(course, scheme.name)] = cohorts.bands(course, scheme.name, [g.as_dict() for g in scheme.grades])
	frappe.db.set_value(SESSION, exam_session, "frozen_bands", json.dumps(frozen, sort_keys=True), update_modified=False)
	return frozen


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
	"""The release and revision notice templates; an existing (possibly edited) one is left alone."""
	for event, (subject, body) in ((RELEASE_EVENT, RELEASE_TEMPLATE), (REVISED_EVENT, REVISED_TEMPLATE)):
		if frappe.db.exists("Message Template", event):
			continue
		frappe.get_doc(
			{
				"doctype": "Message Template", "event_key": event, "purpose": "transactional",
				"channels": [{"channel": "sms"}, {"channel": "whatsapp"}, {"channel": "email"}],
				"bodies": [{"language": "en", "subject": subject, "body": body}],
			}
		).insert(ignore_permissions=True)  # fmt: skip
