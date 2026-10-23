"""M05-12 integration tests: attendance start date, class session states, On Duty / medical leave covering sessions,
and the eligibility (condonation, eligibility run snapshot that hall tickets read) on the adjusted percentage.
Marking, state changes and corrections after the cut-off are in test_attendance_corrections."""

import frappe
from frappe.utils import add_days

from campus.student_services import eligibility_run
from campus.student_services.api import attendance_snapshot, attendance_summary, eligibility_status
from campus.tests.factories import make_company
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Session Test College"
PROGRAM = "Session Test BE"
COURSE = "SES A"
TERM = "Ses Odd"
FIRST_DAY = "2022-06-06"
RULE = {
	"formula": "sum_based", "overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 0,
	"od_counts": 1, "medical_counts": 1, "condonation_fee": 0,
}  # fmt: skip
STUDENTS = ("main", "late", "duty", "medic", "cond")


def clear_world():
	students = frappe.get_all("Student", {"oc_company": COLLEGE}, pluck="name") or [""]
	groups = frappe.get_all("Student Group", {"oc_company": COLLEGE}, pluck="name") or [""]
	for doctype, filters in (
		("Student Attendance", {"student": ["in", students]}),
		("Student Leave Application", {"student": ["in", students]}),
		("Condonation Request", {"student": ["in", students]}),
		("Attendance Eligibility Run", {"company": COLLEGE}),
		("Course Schedule", {"student_group": ["in", groups]}),
		("Student Group Student", {"parent": ["in", groups]}),
		("Student Group", {"name": ["in", groups]}),
		("Program Enrollment", {"student": ["in", students]}),
		("Student", {"name": ["in", students]}),
		("Attendance Rule", {"regulation": ["like", "%-SES%"]}),
	):
		frappe.db.delete(doctype, filters)


def make_term():
	name = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": TERM})
	return name or frappe.get_doc(
		{
			"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": TERM,
			"term_start_date": "2022-06-01", "term_end_date": "2022-11-30",
		}
	).insert().name  # fmt: skip


def make_sessions(group, days):
	"""A Course Schedule of the group on each of the term days `days` (numbers from FIRST_DAY)."""
	names = []
	for day in days:
		doc = frappe.get_doc({"doctype": "Course Schedule", "student_group": group, "course": COURSE, "schedule_date": add_days(FIRST_DAY, day)})
		doc.flags.ignore_validate = True  # Education's room, instructor and clash checks are not under test
		names.append(doc.insert(ignore_permissions=True, ignore_mandatory=True).name)
	return names


def set_state(session, state, **links):
	frappe.db.set_value("Course Schedule", session, {"oc_session_state": state, **links})


def mark(student, session, status):
	schedule = frappe.db.get_value("Course Schedule", session, ["student_group", "schedule_date"], as_dict=True)
	doc = frappe.get_doc(
		{
			"doctype": "Student Attendance", "student": student, "student_group": schedule.student_group, "course_schedule": session,
			"date": schedule.schedule_date, "status": status,
		}
	)  # fmt: skip
	doc.flags.ignore_validate = True  # holiday list and group checks are Education's
	doc.insert(ignore_permissions=True)
	doc.submit()


def approved_leave(student, day, kind, **scope):
	doc = frappe.get_doc(
		{
			"doctype": "Student Leave Application", "student": student, "from_date": add_days(FIRST_DAY, day), "to_date": add_days(FIRST_DAY, day),
			"oc_leave_kind": kind, **scope,
		}
	)  # fmt: skip
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Student Leave Application", doc.name, "docstatus", 1)  # Education's on_submit needs a holiday list
	return doc.name


class TestAttendanceSessions(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_world()
		make_company(COLLEGE, "SESC")
		make_year("2022")
		make_program(PROGRAM, COLLEGE)
		regulation = make_regulation("R2022-SES", COLLEGE, [PROGRAM], "2022").name
		cls.rule = frappe.get_doc({"doctype": "Attendance Rule", "regulation": regulation, **RULE}).insert().name
		if not frappe.db.exists("Course", COURSE):
			frappe.get_doc({"doctype": "Course", "course_name": COURSE, "oc_company": COLLEGE}).insert()
		cls.term = make_term()
		cls.enrollments = {}
		for key in STUDENTS:
			student = make_student(f"Ses{key.title()}", COLLEGE, "2022")
			setattr(cls, key, student.name)
			cls.enrollments[key] = enroll(student, PROGRAM, "2022").name  # a draft: it assigns the regulation

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def offering(self, *students):
		return frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": f"SES {frappe.generate_hash(length=6)}", "group_based_on": "Course",
				"academic_year": year_name("2022"), "academic_term": self.term, "program": PROGRAM, "course": COURSE,
				"oc_company": COLLEGE, "students": [{"student": s} for s in students],
			}
		).insert().name  # fmt: skip

	def row(self, student, offering):
		"""(conducted, attended, medical leave) of the student in the offering."""
		row = next(r for r in attendance_summary(student, self.term)["offerings"] if r["offering"] == offering)
		return row["conducted"], row["attended"], row["leave"]

	def set_rule(self, fieldname, value):
		before = frappe.db.get_value("Attendance Rule", self.rule, fieldname)
		frappe.db.set_value("Attendance Rule", self.rule, fieldname, value)
		self.addCleanup(frappe.db.set_value, "Attendance Rule", self.rule, fieldname, before)

	def test_a_late_joiner_is_not_absent_before_the_start_date(self):
		group = self.offering(self.main, self.late)
		sessions = make_sessions(group, range(10))
		for n, session in enumerate(sessions):
			mark(self.main, session, "Present" if n < 8 else "Absent")
		for session in sessions[5:]:
			mark(self.late, session, "Present")
		self.assertEqual(self.row(self.late, group), (10, 5, 0))  # no start date yet: the whole term counts
		frappe.db.set_value(
			"Program Enrollment", self.enrollments["late"], {"docstatus": 1, "oc_attendance_start_date": add_days(FIRST_DAY, 5)}
		)  # joined on day 5 (the joining confirmation sets this date)
		self.addCleanup(frappe.db.set_value, "Program Enrollment", self.enrollments["late"], "docstatus", 0)
		self.assertEqual(self.row(self.late, group), (5, 5, 0))
		self.assertEqual(self.row(self.main, group), (10, 8, 0))  # classmates keep the whole term
		frappe.db.set_value("Program Enrollment", self.enrollments["late"], "oc_attendance_start_date", "2023-01-02")
		self.assertEqual(self.row(self.late, group), (10, 5, 0))  # a start after the term is not this term's joining

	def test_a_cancelled_session_drops_out_of_the_denominator(self):
		group = self.offering(self.main)
		sessions = make_sessions(group, range(4))
		for n, session in enumerate(sessions):
			mark(self.main, session, "Absent" if n == 3 else "Present")
		self.assertEqual(self.row(self.main, group), (4, 3, 0))
		set_state(sessions[3], "Cancelled")
		self.assertEqual(self.row(self.main, group), (3, 3, 0))  # its Absent mark no longer counts either

	def test_a_rescheduled_session_counts_once_on_the_new_date(self):
		group = self.offering(self.main)
		moved, kept, new = make_sessions(group, (1, 2, 8))
		mark(self.main, moved, "Absent")  # marked before it was moved
		mark(self.main, kept, "Present")
		mark(self.main, new, "Present")
		set_state(moved, "Rescheduled", oc_rescheduled_to=new)
		self.assertEqual(self.row(self.main, group), (2, 2, 0))

	def test_a_makeup_replaces_the_session_it_is_for(self):
		group = self.offering(self.main)
		missed, held, makeup = make_sessions(group, (2, 3, 9))
		mark(self.main, held, "Present")
		mark(self.main, makeup, "Present")
		self.assertEqual(self.row(self.main, group), (3, 2, 0))
		set_state(makeup, "Makeup", oc_makeup_for=missed)
		self.assertEqual(self.row(self.main, group), (2, 2, 0))

	def test_on_duty_leave_covering_a_session_counts_as_the_rule_says(self):
		group = self.offering(self.duty)
		first, second = make_sessions(group, (4, 5))
		mark(self.duty, first, "Present")
		mark(self.duty, second, "Absent")  # marked absent, then the On Duty application was approved
		self.assertEqual(self.row(self.duty, group), (2, 1, 0))
		approved_leave(self.duty, 5, "On Duty")
		self.assertEqual(self.row(self.duty, group), (2, 2, 0))
		self.set_rule("od_counts", 0)
		self.assertEqual(self.row(self.duty, group), (2, 1, 0))

	def test_medical_leave_covering_a_session_counts_as_the_rule_says(self):
		group = self.offering(self.medic)
		first, second = make_sessions(group, (6, 7))
		mark(self.medic, first, "Present")  # the second session is not marked for the student at all
		approved_leave(self.medic, 7, "Medical")
		self.assertEqual(self.row(self.medic, group), (2, 1, 1))  # medical leave counts in the band decision only
		self.set_rule("medical_counts", 0)
		self.assertEqual(self.row(self.medic, group), (2, 1, 0))

	def test_condonation_and_the_eligibility_snapshot_use_the_adjusted_percentage(self):
		group = self.offering(self.cond)
		sessions = make_sessions(group, range(10))
		for n, session in enumerate(sessions):
			mark(self.cond, session, "Present" if n < 7 else "Absent")
		self.assertEqual(eligibility_status(self.cond, self.term), "Shortage")  # 7 of 10
		request = {"doctype": "Condonation Request", "student": self.cond, "academic_term": self.term, "reason": "Ill"}
		with self.assertRaisesRegex(frappe.ValidationError, "below the medical band"):
			frappe.get_doc(request).insert()
		for session in sessions[8:]:
			set_state(session, "Cancelled")
		self.assertEqual(eligibility_status(self.cond, self.term), "Eligible")  # 7 of 8 = 87.5
		with self.assertRaisesRegex(frappe.ValidationError, "no condonation is needed"):
			frappe.get_doc(request).insert()
		run = frappe.get_doc({"doctype": "Attendance Eligibility Run", "company": COLLEGE, "academic_term": self.term}).insert()
		eligibility_run.run_student(self.cond, frappe._dict(get_parameters=lambda: {"run": run.name}))
		self.assertEqual(frappe.db.get_value("Attendance Eligibility Row", {"parent": run.name, "student": self.cond}, "overall_pct"), 87.5)
		run.db_set("locked", 1)
		self.assertEqual(attendance_snapshot(self.cond, self.term, COLLEGE), "Eligible")  # what exam registration and hall tickets read

	def test_a_makeup_still_to_come_does_not_replace_its_session_yet(self):
		group = self.offering(self.main)
		missed, held, makeup = make_sessions(group, (12, 13, 200))  # day 200 is after the term's counted window
		mark(self.main, held, "Present")
		set_state(makeup, "Makeup", oc_makeup_for=missed)
		self.assertEqual(self.row(self.main, group), (2, 1, 0))

	def test_a_leave_for_another_student_group_does_not_cover_the_session(self):
		group, other = self.offering(self.duty), self.offering(self.duty)
		(session,) = make_sessions(group, (20,))
		mark(self.duty, session, "Absent")
		approved_leave(self.duty, 20, "On Duty", attendance_based_on="Student Group", student_group=other)
		self.assertEqual(self.row(self.duty, group), (1, 0, 0))
		approved_leave(self.duty, 20, "On Duty", attendance_based_on="Student Group", student_group=group)
		self.assertEqual(self.row(self.duty, group), (1, 1, 0))

	def test_a_leave_marked_as_present_makes_the_session_present(self):
		group = self.offering(self.medic)
		(session,) = make_sessions(group, (21,))
		mark(self.medic, session, "Absent")
		approved_leave(self.medic, 21, "Medical", mark_as_present=1)
		self.assertEqual(self.row(self.medic, group), (1, 1, 0))  # Present, not medical leave

	def test_a_record_without_a_session_counts_for_the_days_first_session_only(self):
		group = self.offering(self.main)
		make_sessions(group, (22, 22))
		doc = frappe.get_doc(
			{"doctype": "Student Attendance", "student": self.main, "student_group": group, "date": add_days(FIRST_DAY, 22), "status": "Present"}
		)
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True).submit()
		self.assertEqual(self.row(self.main, group), (2, 1, 0))
