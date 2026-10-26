"""M17-06 integration tests of the COE reports and the data points days_exam_to_result, students_appeared,
pass_percentage (with final_year_passed and evaluation_grievances): each data point equals its report.

Fixture world: campus.tests.test_results.ExamFixture, the session flagged final-year, its exam ending 2023-02-20 and
published 2023-03-12 (20 days). With s26's EXM FA ESE raised to 40 / 60: s22 fails EXM FA (ESE 44 %), s26 passes
every course, s_ab was absent from EXM TH and fails EXM FA, s_sa is short of attendance (every course SA).
Appeared: s22, s26, s_ab (3); passed every course: s26 (1); pass percentage 1 / 3 = 33.33.
"""

from unittest.mock import patch

import frappe

from campus.examinations import results
from campus.examinations.report.arrear_list.arrear_list import execute as arrear_report
from campus.examinations.report.days_exam_end_to_result.days_exam_end_to_result import execute as days_report
from campus.examinations.report.evaluation_grievances_vs_appeared.evaluation_grievances_vs_appeared import (
	execute as grievance_report,
)
from campus.examinations.report.exam_absentee_list.exam_absentee_list import execute as absentee_report
from campus.examinations.report.exam_eligibility_withheld.exam_eligibility_withheld import (
	execute as withheld_report,
)
from campus.examinations.report.exam_registration_summary.exam_registration_summary import (
	execute as registration_report,
)
from campus.examinations.report.malpractice_register.malpractice_register import execute as malpractice_report
from campus.examinations.report.rank_list.rank_list import execute as rank_report
from campus.examinations.report.result_analysis.result_analysis import execute as analysis_report
from campus.examinations.report.valuation_difference.valuation_difference import execute as difference_report
from campus.examinations.report.valuation_progress.valuation_progress import execute as progress_report
from campus.iqac.registry import data_point
from campus.tests.test_regulation import year_name
from campus.tests.test_results import COE_USER, COLLEGE, PROGRAM, ExamFixture

YEAR = year_name("2022")


def make_department(name):
	"""A leaf Department of the test college (named `<name> - <abbr>` by ERPNext)."""
	found = frappe.db.get_value("Department", {"department_name": name, "company": COLLEGE})
	return (
		found
		or frappe.get_doc({"doctype": "Department", "department_name": name, "company": COLLEGE})
		.insert()
		.name
	)


EXAM_END, PUBLISHED_AT = "2023-02-20", "2023-03-12 10:00:00"
SCOPE = "campus.examinations.coe_reports.permitted_companies"


def insert(values):
	"""Insert a report source row as stored data, without its controller (the reports only read it)."""
	doc = frappe.get_doc(values)
	doc.db_insert()
	for child in doc.get_all_children():
		child.db_insert()
	return doc


class COEReportFixture(ExamFixture):
	def setUp(self):
		super().setUp()
		sheets = frappe.get_all(
			"Mark Sheet Entry", {"exam_session": self.session.name, "course": "EXM FA"}, pluck="name"
		)
		frappe.db.set_value(
			"Mark Sheet Entry Row", {"parent": ["in", sheets], "student": self.s26.name}, "ese", 40
		)
		self.run_session()
		frappe.db.set_value("Exam Session", self.session.name, {"is_final_year": 1, "exam_end": EXAM_END})
		self.publish(PUBLISHED_AT)

	def as_coe(self, report, filters):
		frappe.set_user(COE_USER)
		try:
			return report(filters)[1]
		finally:
			frappe.set_user("Administrator")

	def result_name(self, student):
		return frappe.db.get_value(
			"Student Result", {"student": student.name, "exam_session": self.session.name, "is_latest": 1}
		)


class TestResultDataPoints(COEReportFixture):
	def test_students_appeared_is_the_grievance_report_total(self):
		point = data_point("students_appeared", COLLEGE, YEAR)
		appeared = sorted(s.name for s in (self.s22, self.s26, self.s_ab))
		self.assertEqual(point["value"], 3)
		self.assertEqual(point["records"], [{"doctype": "Student", "name": s} for s in appeared])
		total = self.as_coe(grievance_report, {"company": COLLEGE, "academic_year": YEAR})[-1]
		self.assertEqual(total["appeared"], point["value"])
		self.assertEqual(data_point("evaluation_grievances", COLLEGE, YEAR)["value"], total["grievances"])

	def test_pass_percentage_is_the_final_year_result_analysis_total(self):
		point = data_point("pass_percentage", COLLEGE, YEAR)
		self.assertEqual(point["value"], 33.33)
		appeared = sorted(self.result_name(s) for s in (self.s22, self.s26, self.s_ab))
		self.assertEqual(point["records"], [{"doctype": "Student Result", "name": n} for n in appeared])
		rows = self.as_coe(
			analysis_report,
			{"company": COLLEGE, "academic_year": YEAR, "group_by": "Program", "final_year_only": 1},
		)
		self.assertEqual(
			[(r["group"], r["appeared"], r["passed"], r["pass_pct"]) for r in rows[:-1]],
			[(PROGRAM, 3, 1, 33.33)],
		)
		self.assertEqual(
			(rows[-1]["appeared"], rows[-1]["passed"], rows[-1]["pass_pct"]), (3, 1, point["value"])
		)
		self.assertEqual(data_point("final_year_passed", COLLEGE, YEAR)["value"], rows[-1]["passed"])
		self.assertEqual(data_point("final_year_appeared", COLLEGE, YEAR)["value"], rows[-1]["appeared"])

	def test_result_analysis_by_course_counts_each_sitting(self):
		rows = self.as_coe(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Course"})
		by_course = {r["group"]: (r["appeared"], r["passed"], r["pass_pct"]) for r in rows[:-1]}
		# EXM FA: s22 and s_ab fail, s26 passes; EXM TH: s_ab absent; s_sa never sat
		self.assertEqual(
			by_course,
			{"EXM FA": (3, 1, 33.33), "EXM TH": (2, 2, 100), "EXM LB": (3, 3, 100), "EXM TL": (3, 3, 100)},
		)
		self.assertEqual((rows[-1]["appeared"], rows[-1]["passed"]), (11, 9))

	def test_not_final_year_has_no_pass_percentage_but_students_still_appeared(self):
		frappe.db.set_value("Exam Session", self.session.name, "is_final_year", 0)
		self.assertEqual(data_point("pass_percentage", COLLEGE, YEAR)["value"], 0)
		self.assertEqual(data_point("students_appeared", COLLEGE, YEAR)["value"], 3)

	def test_an_unpublished_session_counts_nowhere(self):
		frappe.db.set_value("Exam Session", self.session.name, "status", "Marks Entry")
		for key in ("students_appeared", "pass_percentage", "days_exam_to_result"):
			self.assertEqual(data_point(key, COLLEGE, YEAR)["value"], 0, key)
		self.assertEqual(
			self.as_coe(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Program"}),
			[],
		)

	def test_a_result_version_awaiting_ratification_is_not_counted(self):
		# a re-run after publication (e.g. a revaluation) gives s22 a pending V2 passing EXM FA; V1 stays the published one
		sheets = frappe.get_all(
			"Mark Sheet Entry", {"exam_session": self.session.name, "course": "EXM FA"}, pluck="name"
		)
		frappe.db.set_value(
			"Mark Sheet Entry Row", {"parent": ["in", sheets], "student": self.s22.name}, "ese", 40
		)
		pending = results.compute_student_result(self.s22.name, self.session.name)
		self.assertEqual(
			frappe.db.get_value("Student Result", pending, ["version", "pending_ratification", "is_latest"]),
			(2, 1, 0),
		)
		self.assertEqual(data_point("final_year_passed", COLLEGE, YEAR)["value"], 1)  # still s26 only
		self.assertEqual(data_point("pass_percentage", COLLEGE, YEAR)["value"], 33.33)
		point = data_point("students_appeared", COLLEGE, YEAR)
		self.assertEqual(point["value"], 3)
		rows = self.as_coe(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Course"})
		self.assertEqual(next(r for r in rows if r["group"] == "EXM FA")["passed"], 1)

	def test_an_embargoed_session_counts_nowhere(self):
		frappe.db.set_value(
			"Exam Session",
			self.session.name,
			"publish_at",
			frappe.utils.add_days(frappe.utils.now_datetime(), 1),
		)
		for key in (
			"students_appeared",
			"pass_percentage",
			"days_exam_to_result",
			"final_year_appeared",
			"final_year_passed",
			"evaluation_grievances",
		):
			self.assertEqual(data_point(key, COLLEGE, YEAR)["value"], 0, key)
		for report, filters in (
			(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Program"}),
			(days_report, {"company": COLLEGE, "academic_year": YEAR}),
			(grievance_report, {"company": COLLEGE, "academic_year": YEAR}),
			(arrear_report, {"company": COLLEGE}),
			(rank_report, {"company": COLLEGE, "exam_session": self.session.name}),
		):
			with self.subTest(report=report.__module__):
				self.assertEqual(self.as_coe(report, filters), [])

	def test_total_rows_sit_in_data_columns(self):
		for report, filters in (
			(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Program"}),
			(days_report, {"company": COLLEGE, "academic_year": YEAR}),
			(grievance_report, {"company": COLLEGE, "academic_year": YEAR}),
		):
			columns, rows = report(filters)
			with self.subTest(report=report.__module__):
				self.assertTrue(rows)
				self.assertEqual(columns[0]["fieldtype"], "Data")

	def test_department_narrows_by_the_program(self):
		ours, other = (make_department(name) for name in ("T24 Exam Dept", "T24 Other Dept"))
		frappe.db.set_value("Program", PROGRAM, "department", ours)
		self.assertEqual(data_point("students_appeared", COLLEGE, YEAR, ours)["value"], 3)
		self.assertEqual(data_point("pass_percentage", COLLEGE, YEAR, ours)["value"], 33.33)
		self.assertEqual(data_point("days_exam_to_result", COLLEGE, YEAR, ours)["value"], 20)
		for key in ("students_appeared", "pass_percentage", "days_exam_to_result"):
			self.assertEqual(data_point(key, COLLEGE, YEAR, other)["value"], 0, key)

	def test_days_exam_to_result_is_the_report_average(self):
		point = data_point("days_exam_to_result", COLLEGE, YEAR)
		self.assertEqual(
			point, {"value": 20, "records": [{"doctype": "Exam Session", "name": self.session.name}]}
		)
		rows = self.as_coe(days_report, {"company": COLLEGE, "academic_year": YEAR})
		self.assertEqual([(r["exam_session"], r["days"]) for r in rows[:-1]], [(self.session.name, 20)])
		self.assertEqual(rows[-1]["days"], point["value"])

	def test_days_fall_back_to_the_last_scheduled_exam(self):
		frappe.db.set_value("Exam Session", self.session.name, "exam_end", None)
		self.assertEqual(
			data_point("days_exam_to_result", COLLEGE, YEAR)["value"], 0
		)  # no end and no schedule: skipped
		insert({"doctype": "Exam Schedule", "parent": self.session.name, "parenttype": "Exam Session", "parentfield": "schedule",
			"course": "EXM TH", "exam_date": "2023-02-27", "slot": "FN"})  # fmt: skip
		self.assertEqual(data_point("days_exam_to_result", COLLEGE, YEAR)["value"], 13)


class TestCOEReports(COEReportFixture):
	def test_rank_list_ranks_the_students_who_passed_every_course(self):
		rows = self.as_coe(rank_report, {"company": COLLEGE, "exam_session": self.session.name})
		self.assertEqual([(r["rank"], r["student"]) for r in rows], [(1, self.s26.name)])

	def test_rank_list_needs_a_released_session(self):
		filters = {"company": COLLEGE, "exam_session": self.session.name}
		frappe.db.set_value(
			"Exam Session",
			self.session.name,
			"publish_at",
			frappe.utils.add_days(frappe.utils.now_datetime(), 1),
		)
		self.assertEqual(self.as_coe(rank_report, filters), [])  # embargoed
		frappe.db.set_value("Exam Session", self.session.name, {"status": "Marks Entry", "publish_at": None})
		self.assertEqual(self.as_coe(rank_report, filters), [])  # unpublished

	def test_arrear_list_names_the_outstanding_courses(self):
		rows = self.as_coe(arrear_report, {"company": COLLEGE})
		arrears = {r["student"]: (r["arrear_count"], r["courses"]) for r in rows}
		self.assertEqual(arrears[self.s22.name], (1, "EXM FA"))
		self.assertEqual(arrears[self.s_ab.name], (2, "EXM FA, EXM TH"))
		self.assertEqual(arrears[self.s_sa.name][0], 4)
		self.assertNotIn(self.s26.name, arrears)

	def test_registration_summary_withheld_and_absentee(self):
		registration = insert({
			"doctype": "Exam Registration", "name": "EXREG-T24-1", "exam_session": self.session.name, "student": self.s_sa.name,
			"program": PROGRAM, "company": COLLEGE, "attendance_status": "Shortage", "confirmed": 1,
			"courses": [{"course": "EXM TH", "kind": "Current", "eligibility": "Not eligible (SA)"},
				{"course": "EXM PRE", "kind": "Arrear", "eligibility": "Eligible"}],
		})  # fmt: skip
		insert({"doctype": "Hall Ticket", "name": "HT-T24-1", "exam_registration": registration.name, "exam_session": self.session.name,
			"student": self.s_sa.name, "program": PROGRAM, "company": COLLEGE, "status": "Withheld",
			"withheld_reasons": "Attendance shortage"})  # fmt: skip
		insert({"doctype": "Seating Plan", "name": "SP-T24-1", "exam_session": self.session.name, "company": COLLEGE,
			"exam_date": "2023-02-20", "slot": "FN", "seats": [
				{"student": self.s_ab.name, "course": "EXM TH", "seat_label": "A1", "absent": 1},
				{"student": self.s22.name, "course": "EXM TH", "seat_label": "A2", "absent": 0}]})  # fmt: skip
		filters = {"company": COLLEGE, "exam_session": self.session.name}
		summary = self.as_coe(registration_report, filters)
		self.assertEqual(
			[
				(
					r["program"],
					r["registrations"],
					r["confirmed"],
					r["shortage"],
					r["current_courses"],
					r["arrear_courses"],
					r["not_eligible_courses"],
				)
				for r in summary
			],
			[(PROGRAM, 1, 1, 1, 1, 1, 1)],
		)
		withheld = self.as_coe(withheld_report, filters)
		self.assertEqual(
			[(r["student"], r["withheld_reasons"], r["not_eligible_courses"]) for r in withheld],
			[(self.s_sa.name, "Attendance shortage", "EXM TH")],
		)
		absent = self.as_coe(absentee_report, filters)
		self.assertEqual(
			[(r["student"], r["course"], r["exam_date"]) for r in absent],
			[(self.s_ab.name, "EXM TH", frappe.utils.getdate("2023-02-20"))],
		)

	def test_malpractice_register_lists_reports_with_the_decision(self):
		insert({"doctype": "Malpractice Report", "name": "MPR-T24-1", "exam_session": self.session.name, "student": self.s22.name,
			"company": COLLEGE, "course": "EXM FA", "exam_date": "2023-02-18", "category": "Copying",
			"committee_decision": "Warning", "docstatus": 1})  # fmt: skip
		insert({"doctype": "Malpractice Report", "name": "MPR-T24-2", "exam_session": self.session.name, "student": self.s26.name,
			"company": COLLEGE, "course": "EXM FA", "category": "Other", "docstatus": 2})  # fmt: skip
		rows = self.as_coe(malpractice_report, {"company": COLLEGE, "exam_session": self.session.name})
		self.assertEqual(
			[(r["name"], r["category"], r["committee_decision"]) for r in rows],
			[("MPR-T24-1", "Copying", "Warning")],
		)

	def test_valuation_progress_and_difference(self):
		for name, round_, deadline in (("VA-T24-1", "1", "2023-02-01"), ("VA-T24-2", "2", "2099-01-01")):
			insert({"doctype": "Valuation Allocation", "name": name, "exam_session": self.session.name, "company": COLLEGE,
				"course": "EXM FA", "valuation_round": round_, "examiner_type": "Internal", "examiner": COE_USER, "deadline": deadline,
				"status": "Allocated", "scripts": [{"dummy_number": "D1"}, {"dummy_number": "D2"}]})  # fmt: skip
		entries = (
			("VE-T24-1", "VA-T24-1", "D1", "1", 30),
			("VE-T24-2", "VA-T24-2", "D1", "2", 42),
			("VE-T24-3", "VA-T24-2", "D2", "2", 20),
		)
		for name, allocation, dummy, round_, total in entries:
			insert({"doctype": "Valuation Entry", "name": name, "allocation": allocation, "dummy_number": dummy, "docstatus": 1,
				"valuation_round": round_, "exam_session": self.session.name, "course": "EXM FA", "total": total})  # fmt: skip
		filters = {"company": COLLEGE, "exam_session": self.session.name}
		progress = self.as_coe(progress_report, filters)
		# round 1 is past its deadline with D2 not valued; round 2 has both scripts in
		self.assertEqual(
			[(r["allocation"], r["scripts"], r["valued"], r["pending"], r["overdue"]) for r in progress],
			[("VA-T24-1", 2, 1, 1, 1), ("VA-T24-2", 2, 2, 0, 0)],
		)
		difference = self.as_coe(difference_report, filters)
		self.assertEqual(
			[(r["dummy_number"], r["first"], r["second"], r["difference"]) for r in difference],
			[("D1", 30, 42, 12)],
		)  # D2 has one valuation only

	def test_every_report_is_empty_outside_the_users_companies(self):
		calls = (
			(analysis_report, {"company": COLLEGE, "academic_year": YEAR, "group_by": "Course"}),
			(days_report, {"company": COLLEGE, "academic_year": YEAR}),
			(rank_report, {"company": COLLEGE, "exam_session": self.session.name}),
			(arrear_report, {"company": COLLEGE}),
			(registration_report, {"company": COLLEGE}),
			(withheld_report, {"company": COLLEGE}),
			(absentee_report, {"company": COLLEGE}),
			(malpractice_report, {"company": COLLEGE}),
			(progress_report, {"company": COLLEGE}),
			(difference_report, {"company": COLLEGE}),
		)
		self.assertTrue(self.as_coe(analysis_report, calls[0][1]))
		with patch(SCOPE, return_value=["Another College"]):
			for report, filters in calls:
				with self.subTest(report=report.__module__):
					self.assertEqual(self.as_coe(report, filters), [])
