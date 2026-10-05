"""M05-02 integration test: attendance_summary under two regulations and the company-scoped shortage report."""

import frappe
from frappe.utils import add_days

from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.student_services.api import attendance_summary, conducted_periods, term_window
from campus.student_services.report.attendance_shortage.attendance_shortage import execute as shortage_report
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Attendance Test College"
OTHER_COLLEGE = "Attendance Other College"
PROGRAM = "Attendance Test BE"
OTHER_PROGRAM = "Attendance Other BE"
COURSES = ["ATT A", "ATT B"]
OTHER_COURSE = "ATT O"
TERM = "Att Odd"
FIRST_DAY = "2022-06-06"
USER = "attendance-staff@example.com"
OTHER_USER = "attendance-other@example.com"
RULES = {
	"R2022": {"formula": "sum_based", "overall_min_pct": 75, "medical_band_min_pct": 65, "per_course_min_pct": 0},
	"R2026": {"formula": "course_average", "overall_min_pct": 80, "medical_band_min_pct": 70, "per_course_min_pct": 75},
}


def clear_world():
	students = frappe.get_all("Student", {"oc_company": ["in", [COLLEGE, OTHER_COLLEGE]]}, pluck="name") or [""]
	frappe.db.delete("Student Attendance", {"student": ["in", students]})
	frappe.db.delete("Student Leave Application", {"student": ["in", students]})
	groups = frappe.get_all("Student Group", {"oc_company": ["in", [COLLEGE, OTHER_COLLEGE]]}, pluck="name") or [""]
	frappe.db.delete("Course Schedule", {"student_group": ["in", groups]})
	frappe.db.delete("Student Group Student", {"parent": ["in", groups]})
	frappe.db.delete("Student Group", {"name": ["in", groups]})
	frappe.db.delete("Program Enrollment", {"student": ["in", students]})
	frappe.db.delete("Student", {"name": ["in", students]})
	frappe.db.delete("Attendance Rule", {"regulation": ["like", "%-ATT"]})


def make_term():
	name = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": TERM})
	return name or frappe.get_doc(
		{
			"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": TERM,
			"term_start_date": "2022-06-01", "term_end_date": "2022-11-30",
		}
	).insert().name  # fmt: skip


def make_offering(course, program, company, students, term):
	if not frappe.db.exists("Course", course):
		frappe.get_doc({"doctype": "Course", "course_name": course, "oc_company": company}).insert()
	return frappe.get_doc(
		{
			"doctype": "Student Group", "student_group_name": f"{course}-{term}", "group_based_on": "Course",
			"academic_year": year_name("2022"), "academic_term": term, "program": program, "course": course,
			"oc_company": company, "students": [{"student": s.name} for s in students],
		}
	).insert().name  # fmt: skip


def mark(student, group, day, status, leave=None):
	"""A submitted Student Attendance row on day number `day` of the term fixture."""
	doc = frappe.get_doc(
		{
			"doctype": "Student Attendance", "student": student, "student_group": group, "status": status,
			"date": add_days(FIRST_DAY, day), "leave_application": leave,
		}
	)  # fmt: skip
	doc.flags.ignore_validate = True  # holiday list and group checks are Education's, not under test
	doc.insert(ignore_permissions=True)
	doc.submit()


def approved_leave(student):
	doc = frappe.get_doc(
		{"doctype": "Student Leave Application", "student": student, "from_date": FIRST_DAY, "to_date": FIRST_DAY}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Student Leave Application", doc.name, "docstatus", 1)  # on_submit needs a holiday list
	return doc.name


def mark_pattern(student, group, present, absent, leave=0, leave_application=None):
	statuses = ["Present"] * present + ["Absent"] * absent + ["Leave"] * leave
	for day, status in enumerate(statuses):
		mark(student, group, day, status, leave_application if status == "Leave" else None)


class TestAttendanceEligibility(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_world()
		make_company(COLLEGE, "ATTC")
		make_company(OTHER_COLLEGE, "ATTO")
		make_user(USER, [COLLEGE])
		make_user(OTHER_USER, [OTHER_COLLEGE])
		for year in ("2022", "2026"):
			make_year(year)
		make_program(PROGRAM, COLLEGE)
		make_program(OTHER_PROGRAM, OTHER_COLLEGE)
		for code, year in (("R2022", "2022"), ("R2026", "2026")):
			regulation = make_regulation(f"{code}-ATT", COLLEGE, [PROGRAM], year).name
			frappe.get_doc({"doctype": "Attendance Rule", "regulation": regulation, **RULES[code]}).insert()
		other_regulation = make_regulation("R2022-ATT", OTHER_COLLEGE, [OTHER_PROGRAM], "2022").name
		frappe.get_doc({"doctype": "Attendance Rule", "regulation": other_regulation, **RULES["R2022"]}).insert()
		cls.term = make_term()
		cls.s22 = make_student("Att22", COLLEGE, "2022")
		cls.s26 = make_student("Att26", COLLEGE, "2026")
		cls.other = make_student("AttOther", OTHER_COLLEGE, "2022")
		for student, program, year in ((cls.s22, PROGRAM, "2022"), (cls.s26, PROGRAM, "2026"), (cls.other, OTHER_PROGRAM, "2022")):
			enroll(student, program, year)
		cls.groups = [make_offering(c, PROGRAM, COLLEGE, [cls.s22, cls.s26], cls.term) for c in COURSES]
		cls.other_group = make_offering(OTHER_COURSE, OTHER_PROGRAM, OTHER_COLLEGE, [cls.other], cls.term)
		cls.leave = approved_leave(cls.s22.name)
		for student in (cls.s22, cls.s26):  # identical raw attendance: A 7 present + 1 leave in 10, B 8 in 10
			mark_pattern(student.name, cls.groups[0], present=7, absent=2, leave=1, leave_application=cls.leave)
			mark_pattern(student.name, cls.groups[1], present=8, absent=2)
		mark_pattern(cls.other.name, cls.other_group, present=5, absent=5)  # a shortage, in another college

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def test_same_attendance_gives_the_regulation_correct_status(self):
		before = attendance_summary(self.s22.name, self.term)
		after = attendance_summary(self.s26.name, self.term)
		self.assertEqual(
			[(r["course"], r["conducted"], r["attended"], r["leave"], r["pct"]) for r in before["offerings"]],
			[("ATT A", 10, 7, 1, 70.0), ("ATT B", 10, 8, 0, 80.0)],
		)
		self.assertEqual((before["overall_pct"], before["status"]), (75.0, "Eligible"))  # 15/20 >= 75
		self.assertEqual((after["overall_pct"], after["status"]), (75.0, "Medical band"))  # mean 75 < 80; leave: 80, 80
		self.assertEqual(after["per_course_min_pct"], 75)

	def test_conducted_prefers_course_schedules(self):
		window = term_window(self.term)
		self.addCleanup(frappe.db.delete, "Course Schedule", {"student_group": self.groups[0]})
		self.assertEqual(conducted_periods(self.groups[0], window), 10)  # distinct marked dates
		for day in range(3):
			schedule = frappe.get_doc(
				{"doctype": "Course Schedule", "student_group": self.groups[0], "schedule_date": add_days(FIRST_DAY, day)}
			)
			schedule.flags.ignore_validate = True  # Education's room and instructor clash checks are not under test
			schedule.insert(ignore_permissions=True, ignore_mandatory=True)
		self.assertEqual(conducted_periods(self.groups[0], window), 3)

	def test_report_lists_only_shortage_and_band_students_of_permitted_companies(self):
		frappe.set_user(USER)
		rows = shortage_report({"company": COLLEGE, "academic_term": self.term})[1]
		self.assertEqual([(r["student"], r["status"], r["overall_pct"]) for r in rows], [(self.s26.name, "Medical band", 75.0)])
		self.assertEqual(shortage_report({"company": OTHER_COLLEGE, "academic_term": self.term})[1], [])
		frappe.set_user(OTHER_USER)
		rows = shortage_report({"company": OTHER_COLLEGE, "academic_term": self.term})[1]
		self.assertEqual([(r["student"], r["status"]) for r in rows], [(self.other.name, "Shortage")])

	def test_summary_is_denied_for_a_student_of_another_company(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			attendance_summary(self.other.name, self.term)
