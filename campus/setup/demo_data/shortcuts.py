"""PR-03 The one place where the demo skips a real control, so a presenter and a reviewer can see exactly what.

Publishing a term's results: a real publication needs a Held, quorate Passing Board meeting and its approving resolution
(`campus.examinations.publication.publish_results`). The demo's 2025-26 terms have no board: the Result Run is computed for
each student by the real service, then the Exam Session is published with `flags.passing_board_approval` set. There is
therefore NO Passing Board record to show for those two terms (walkthrough step 7 says so). The release time and notice
are also dated by the demo, as a past term's would be. Nothing else is skipped: attendance and leave use the real submit paths.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime

from campus.examinations import results


def publish_results(session, students, exam_end=None):
	"""Compute the results of `students` and publish `session` without a Passing Board meeting (see the module docstring)."""
	doc = frappe.get_doc("Exam Session", session)
	if doc.status == "Published":
		return
	for student in students:
		results.compute_student_result(student, session)
	doc.status = "Published"
	doc.publish_at = add_days(now_datetime(), -1)
	doc.exam_end = (
		exam_end or doc.exam_end or getdate(add_days(now_datetime(), -21))
	)  # results 20 days after the last exam (AQAR 2.5.1)
	doc.flags.passing_board_approval = True
	doc.save(ignore_permissions=True)


def date_publication(session, exam_end):
	"""Date the publication like a real term: results fifteen days after the last examination, and no release notice sent
	for a past term."""
	frappe.db.set_value(
		"Exam Session",
		session,
		{"publish_at": f"{add_days(getdate(exam_end), 15)} 10:00:00", "results_notified_on": now_datetime()},
	)
