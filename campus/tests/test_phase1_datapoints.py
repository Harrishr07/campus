"""P1-T27 (M01-02) tests: Phase 1 data points vs hand-computed fixtures and the Live Seat Matrix report."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days

from campus.admissions.report.live_seat_matrix import live_seat_matrix
from campus.iqac import registry
from campus.tests.test_seats_allotments import BC, COLLEGE, GOVT, MBC, MGMT, OC, OTHER_COLLEGE, SUPER, PROGRAM, SeatTestCase, year

DEPARTMENT = "P1T27 Dept"
COURSE = "P1T27 Course"


def point(key, company=COLLEGE, department=None):
	return registry.data_point_keys() and registry.REGISTRY[key](company, year(), department)


class TestPhase1DataPoints(SeatTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Student Category", BC, "oc_is_reserved", 1)
		frappe.db.set_value("Student Category", MBC, "oc_is_reserved", 1)
		frappe.db.set_value("Student Category", OC, "oc_is_reserved", 0)
		self.matrix([(GOVT, OC, 10), (GOVT, BC, 4), (MGMT, BC, 2), (GOVT, MBC, 1), (SUPER, BC, 3)])
		self.enrolments = [self.enrollment(*pair) for pair in ((GOVT, OC), (GOVT, BC), (GOVT, BC), (MGMT, BC), (SUPER, BC), (GOVT, MBC))]

	def test_every_function_is_registered_with_the_company_period_department_signature(self):
		keys = registry.data_point_keys()
		for key in ("reserved_seats_filled", "total_students", "outgoing_students", "programmes_offered", "courses_offered",
			"seats_earmarked_reserved", "scholarship_beneficiaries_govt", "scholarship_beneficiaries_institution", "mentor_ratio"):  # fmt: skip
			self.assertIn(key, keys)
			self.assertEqual(set(point(key)), {"value", "records"})

	def test_seat_metrics_match_the_live_seat_matrix_report(self):
		report = live_seat_matrix.data(frappe._dict(company=COLLEGE, program=PROGRAM, academic_year=year()))
		counted = [r for r in report if not r["supernumerary"] and r["category"] in (BC, MBC)]
		filled, earmarked = point("reserved_seats_filled"), point("seats_earmarked_reserved")
		self.assertEqual(filled["value"], sum(r["filled"] for r in counted))
		self.assertEqual(filled["value"], 4)  # hand count: BC x2 + BC management + MBC; OC and supernumerary excluded
		self.assertEqual(earmarked["value"], sum(r["sanctioned"] for r in counted))
		self.assertEqual(earmarked["value"], 7)  # 4 + 2 + 1, supernumerary row excluded
		names = {r["name"] for r in filled["records"]}
		self.assertEqual(names, {e.name for e in self.enrolments[1:4]} | {self.enrolments[5].name})
		self.assertEqual([r["doctype"] for r in earmarked["records"]], ["Seat Matrix"])

	def test_other_company_and_draft_enrolments_are_not_counted(self):
		self.enrollment(GOVT, BC, submit=False)
		self.assertEqual(point("reserved_seats_filled")["value"], 4)
		self.assertEqual(point("reserved_seats_filled", OTHER_COLLEGE)["value"], 0)
		self.assertEqual(point("total_students", OTHER_COLLEGE)["value"], 0)

	def test_total_students_and_department_filter(self):
		self.assertEqual(point("total_students")["value"], 6)
		self.assertEqual({r["name"] for r in point("total_students")["records"]}, {e.student for e in self.enrolments})
		if not frappe.db.exists("Department", {"department_name": DEPARTMENT, "company": COLLEGE}):
			frappe.get_doc({"doctype": "Department", "department_name": DEPARTMENT, "company": COLLEGE}).insert()
		department = frappe.db.get_value("Department", {"department_name": DEPARTMENT, "company": COLLEGE})
		self.assertEqual(point("total_students", department=department)["value"], 0)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		self.assertEqual(point("total_students", department=department)["value"], 6)
		self.assertEqual(point("programmes_offered", department=department)["value"], 1)

	def test_outgoing_students_are_those_leaving_in_the_year(self):
		start = frappe.db.get_value("Academic Year", year(), "year_start_date")
		leaver, stayer = self.enrolments[0].student, self.enrolments[1].student
		frappe.db.set_value("Student", leaver, "date_of_leaving", add_days(start, 30))
		frappe.db.set_value("Student", stayer, "date_of_leaving", add_days(start, -30))  # left the year before
		result = point("outgoing_students")
		self.assertEqual((result["value"], result["records"]), (1, [{"doctype": "Student", "name": leaver}]))

	def test_programmes_offered_counts_programs_with_a_seat_matrix(self):
		self.assertEqual(point("programmes_offered"), {"value": 1, "records": [{"doctype": "Program", "name": PROGRAM}]})
		self.assertEqual(point("programmes_offered", OTHER_COLLEGE)["value"], 0)

	def test_courses_offered_counts_distinct_courses_of_course_groups(self):
		for index in (1, 2):
			frappe.get_doc({"doctype": "Student Group", "student_group_name": f"P1T27 Group {index}",
				"group_based_on": "Course", "program": PROGRAM, "course": self.course(), "academic_year": year(),
				"oc_company": COLLEGE}).insert()  # fmt: skip
		self.assertEqual(point("courses_offered"), {"value": 1, "records": [{"doctype": "Course", "name": COURSE}]})

	def course(self):
		if not frappe.db.exists("Course", COURSE):
			frappe.get_doc({"doctype": "Course", "course_name": COURSE, "oc_company": COLLEGE}).insert()
		return COURSE

	def test_mentor_ratio_is_mentored_students_per_mentor(self):
		self.assertEqual(point("mentor_ratio"), {"value": 0, "records": []})
		students = [e.student for e in self.enrolments]
		for student, mentor in zip(students[:3], ("EMP-A", "EMP-A", "EMP-B"), strict=True):
			frappe.db.set_value("Student", student, "oc_mentor", mentor)
		result = point("mentor_ratio")
		self.assertEqual(result["value"], 1.5)  # 3 mentored students / 2 mentors
		self.assertEqual({r["name"] for r in result["records"]}, set(students[:3]))

	def test_scholarship_beneficiaries_reuse_the_aqar_511_512_functions(self):
		self.assertIs(registry.REGISTRY["scholarship_beneficiaries_govt"], registry.REGISTRY["scholarship_govt_students"])
		self.assertIs(registry.REGISTRY["scholarship_beneficiaries_institution"], registry.REGISTRY["scholarship_inst_students"])
		rows = [frappe._dict(name="SA-1", student="S1"), frappe._dict(name="SA-2", student="S1"), frappe._dict(name="SA-3", student="S2")]
		with patch("campus.iqac.datapoints.scholarship_beneficiaries", return_value=rows) as report:
			result = point("scholarship_beneficiaries_govt")
		report.assert_called_once_with(COLLEGE, year(), "Government")
		self.assertEqual(result["value"], 2)  # distinct students
		self.assertEqual([r["name"] for r in result["records"]], ["SA-1", "SA-2", "SA-3"])
