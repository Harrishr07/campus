"""P1-T27 (M01-02) tests: Phase 1 data points vs hand-computed fixtures and the Live Seat Matrix report."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days

from campus.admissions.report.live_seat_matrix import live_seat_matrix
from campus.iqac import registry
from campus.tests import test_scholarships as sch
from campus.tests.finance_factories import make_enrolled_students, make_year_and_program
from campus.tests.test_scholarships import ScholarshipFixture
from campus.tests.test_seats_allotments import (
	BC,
	COLLEGE,
	GOVT,
	MBC,
	MGMT,
	OC,
	OTHER_COLLEGE,
	PROGRAM,
	SUPER,
	SeatTestCase,
	year,
)

DEPARTMENT = "P1T27 Dept"
COURSE = "P1T27 Course"


def point(key, company=COLLEGE, department=None):
	return registry.data_point(key, company, year(), department)


def make_department(name, company):
	filters = {"department_name": name, "company": company}
	if not frappe.db.exists("Department", filters):
		frappe.get_doc({"doctype": "Department", **filters}).insert()
	return frappe.db.get_value("Department", filters)


class TestPhase1DataPoints(SeatTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Student Category", BC, "oc_is_reserved", 1)
		frappe.db.set_value("Student Category", MBC, "oc_is_reserved", 1)
		frappe.db.set_value("Student Category", OC, "oc_is_reserved", 0)
		self.matrix([(GOVT, OC, 10), (GOVT, BC, 4), (MGMT, BC, 2), (GOVT, MBC, 1), (SUPER, BC, 3)])
		self.enrolments = [
			self.enrollment(*pair)
			for pair in ((GOVT, OC), (GOVT, BC), (GOVT, BC), (MGMT, BC), (SUPER, BC), (GOVT, MBC))
		]

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
		self.assertEqual(
			filled["value"], 4
		)  # hand count: BC x2 + BC management + MBC; OC and supernumerary excluded
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
		self.assertEqual(
			{r["name"] for r in point("total_students")["records"]}, {e.student for e in self.enrolments}
		)
		department = make_department(DEPARTMENT, COLLEGE)
		self.assertEqual(point("total_students", department=department)["value"], 0)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		self.assertEqual(point("total_students", department=department)["value"], 6)
		self.assertEqual(point("programmes_offered", department=department)["value"], 1)

	def test_outgoing_students_left_with_a_tc_in_the_year_and_were_not_cancelled(self):
		start = frappe.db.get_value("Academic Year", year(), "year_start_date")
		in_year, year_before = add_days(start, 30), add_days(start, -30)
		leaver, earlier, no_tc, cancelled, draft_cancel = (e.student for e in self.enrolments[:5])
		self.leave(leaver, in_year, "TC-1")
		self.leave(earlier, year_before, "TC-2")  # left the year before
		self.leave(
			no_tc, in_year, None
		)  # date of leaving without a TC (an admission cancellation sets only the date)
		self.leave(cancelled, in_year, "TC-3")
		self.leave(draft_cancel, in_year, "TC-4")
		self.cancellation(self.enrolments[3], docstatus=1)
		self.cancellation(self.enrolments[4], docstatus=0)  # only a submitted cancellation excludes
		result = point("outgoing_students")
		self.assertEqual(result["value"], 2)
		self.assertEqual({r["name"] for r in result["records"]}, {leaver, draft_cancel})
		department = make_department(DEPARTMENT, COLLEGE)
		self.assertEqual(point("outgoing_students", department=department)["value"], 0)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		self.assertEqual(point("outgoing_students", department=department)["value"], 2)

	def leave(self, student, date, certificate):
		frappe.db.set_value(
			"Student", student, {"date_of_leaving": date, "leaving_certificate_number": certificate}
		)

	def cancellation(self, enrolment, docstatus):
		"""An Admission Cancellation row of the given docstatus (its refund workflow is T16's and not exercised here)."""
		doc = frappe.get_doc({"doctype": "Admission Cancellation", "student": enrolment.student, "company": COLLEGE,
			"program_enrollment": enrolment.name, "cancellation_date": enrolment.enrollment_date, "docstatus": docstatus})  # fmt: skip
		doc.name = f"P1T27-CAN-{frappe.generate_hash(length=8)}"
		doc.db_insert()

	def test_programmes_offered_counts_programs_with_a_seat_matrix(self):
		self.assertEqual(
			point("programmes_offered"), {"value": 1, "records": [{"doctype": "Program", "name": PROGRAM}]}
		)
		self.assertEqual(point("programmes_offered", OTHER_COLLEGE)["value"], 0)

	def test_courses_offered_counts_distinct_courses_of_course_groups(self):
		for index in (1, 2):
			frappe.get_doc({"doctype": "Student Group", "student_group_name": f"P1T27 Group {index}",
				"group_based_on": "Course", "program": PROGRAM, "course": self.course(), "academic_year": year(),
				"oc_company": COLLEGE}).insert()  # fmt: skip
		self.assertEqual(
			point("courses_offered"), {"value": 1, "records": [{"doctype": "Course", "name": COURSE}]}
		)

	def course(self):
		if not frappe.db.exists("Course", COURSE):
			frappe.get_doc({"doctype": "Course", "course_name": COURSE, "oc_company": COLLEGE}).insert()
		return COURSE

	def test_mentor_ratio_is_enrolled_students_per_active_mentor(self):
		students = [e.student for e in self.enrolments]
		self.assertEqual(point("mentor_ratio")["value"], 0)  # no mentor assigned yet
		active_a, active_b, left = (self.employee(f"P1T27 Mentor {n}") for n in "ABC")
		frappe.db.set_value(
			"Employee",
			left,
			{"status": "Left", "relieving_date": add_days(self.enrolments[0].enrollment_date, 1)},
		)
		for student, mentor in zip(students[:4], (active_a, active_a, active_b, left), strict=True):
			frappe.db.set_value("Student", student, "oc_mentor", mentor)
		result = point("mentor_ratio")
		self.assertEqual(result["value"], 3)  # NAAC 2.3.3: 6 enrolled students / 2 active mentors
		self.assertEqual({r["name"] for r in result["records"]}, set(students))
		department = make_department(DEPARTMENT, COLLEGE)
		self.assertEqual(point("mentor_ratio", department=department), {"value": 0, "records": []})

	def employee(self, first_name):
		if not frappe.db.exists("Gender", "Female"):
			frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
		return frappe.get_doc({"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": first_name, "gender": "Female",
			"date_of_birth": "1980-01-01", "date_of_joining": "2015-06-01", "status": "Active", "company": COLLEGE,
			"create_user_permission": 0}).insert().name  # fmt: skip

	def test_thin_slice_data_points_take_a_department(self):
		self.assertEqual(point("students_admitted")["value"], 6)
		department = make_department(DEPARTMENT, COLLEGE)
		for key in ("students_admitted", "final_year_appeared", "final_year_passed"):
			self.assertEqual(point(key, department=department), {"value": 0, "records": []}, key)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		self.assertEqual(point("students_admitted", department=department)["value"], 6)

	def test_scholarship_beneficiaries_reuse_the_aqar_511_512_functions(self):
		self.assertIs(
			registry.REGISTRY["scholarship_beneficiaries_govt"],
			registry.REGISTRY["scholarship_govt_students"],
		)
		self.assertIs(
			registry.REGISTRY["scholarship_beneficiaries_institution"],
			registry.REGISTRY["scholarship_inst_students"],
		)
		rows = [
			frappe._dict(name="SA-1", student="S1"),
			frappe._dict(name="SA-2", student="S1"),
			frappe._dict(name="SA-3", student="S2"),
		]
		with patch("campus.iqac.datapoints.scholarship_beneficiaries", return_value=rows) as report:
			result = point("scholarship_beneficiaries_govt")
		report.assert_called_once_with(COLLEGE, year(), "Government")
		self.assertEqual(result["value"], 2)  # distinct students
		self.assertEqual([r["name"] for r in result["records"]], ["SA-1", "SA-2", "SA-3"])


class TestScholarshipDepartment(ScholarshipFixture):
	"""Scholarship beneficiaries narrowed by the department of the student's program (real T22 applications)."""

	def test_department_keeps_the_beneficiaries_enrolled_in_its_programs(self):
		other_program = "Scholarship Test ME"
		make_year_and_program(sch.COLLEGE, other_program, sch.YEAR)
		_group, (outsider,) = make_enrolled_students(sch.COLLEGE, other_program, sch.YEAR, 1, "SchDept")
		inside = self.application(self.a, self.govt)
		self.application(outsider, self.govt)
		institutional = self.application(self.b, self.inst)
		department = make_department(DEPARTMENT, sch.COLLEGE)
		frappe.db.set_value("Program", sch.PROGRAM, "department", department)

		def students(key, department=None):
			result = registry.data_point(key, sch.COLLEGE, sch.YEAR, department)
			return result["value"], [r["name"] for r in result["records"]]

		self.assertEqual(students("scholarship_beneficiaries_govt")[0], 2)
		self.assertEqual(students("scholarship_beneficiaries_govt", department), (1, [inside.name]))
		self.assertEqual(
			students("scholarship_beneficiaries_institution", department), (1, [institutional.name])
		)
		empty = make_department("P1T27 Empty Dept", sch.COLLEGE)
		self.assertEqual(students("scholarship_beneficiaries_govt", empty), (0, []))
