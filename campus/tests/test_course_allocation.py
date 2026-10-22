"""P2-T06 (M07-02) tests: the workload rules, Course Allocation checks (AC1 overload warn / block / Dean override,
AC2 every offering has faculty), HOD approval, instructor sync on the Student Groups, and the Workload Balance report.

Fixture: the demo's CSE teachers, one test Faculty Norm in force for the test term (weekly hours min-max, block margin 2):
Professor 4-8, Associate Professor 5-10, Assistant Professor 6-12. Four CSE offerings O1-O4 and one ECE offering O5.
Hours are Lecture + Tutorial + Practical; every expected figure is hand-computed in the comments.
"""

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.approval_engine import latest_request
from campus.faculty import workload
from campus.faculty.setup import seed_course_allocation_policy
from campus.faculty.report.workload_balance.workload_balance import execute as balance_report
from campus.faculty.report.workload_balance.workload_balance import status_of
from campus.tests import demo
from campus.tests.factories import make_user
from campus.tests.utils import CampusTestCase

TERM = "WL Test Odd"
CSE = f"{demo.CSE_DEPARTMENT} - DCE"  # demo.department_name, which needs the company to exist already
ECE = f"{demo.ECE_DEPARTMENT} - DCE"
DEAN = "wl-dean@example.com"
ECE_HOD = "wl-hod-ece@example.com"
HOD, PROFESSOR, ASSOCIATE, ASSISTANT_A, ASSISTANT_B = "hod_cse", "hod_cse", "faculty_1", "faculty_2", "faculty_3"
# offering, teacher, lecture, tutorial, practical
BASE = [
	("O1", PROFESSOR, 3, 0, 0),  # Professor: 3 (min 4) -> Under
	("O1", ASSOCIATE, 0, 1, 0), ("O2", ASSOCIATE, 3, 0, 2),  # Associate: 1 + 5 = 6 (5-10) -> Within
	("O3", ASSISTANT_A, 3, 0, 0),  # Assistant A: 3 (min 6) -> Under
	("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 4, 1, 2),  # Assistant B: 6 + 7 = 13 (max 12) -> Over, within 12 + 2
]  # fmt: skip


class TestWorkloadRules(UnitTestCase):
	def test_classify_against_the_maximum_and_the_margin(self):
		self.assertEqual(workload.classify(12, 12, 2), workload.OK)
		self.assertEqual(workload.classify(12.5, 12, 2), workload.WARN)
		self.assertEqual(workload.classify(14, 12, 2), workload.WARN)  # max + 2 itself only warns
		self.assertEqual(workload.classify(14.5, 12, 2), workload.BLOCK)
		self.assertEqual(workload.classify(12.5, 12, 0), workload.BLOCK)

	def test_no_maximum_means_no_limit(self):
		self.assertEqual(workload.classify(40, 0, 2), workload.OK)

	def test_row_hours_and_faculty_totals(self):
		rows = [
			frappe._dict(faculty="a", lecture_hours=3, tutorial_hours=1, practical_hours=2),
			frappe._dict(faculty="b", lecture_hours=2, tutorial_hours=None, practical_hours=None),
			frappe._dict(faculty="a", lecture_hours=4, tutorial_hours=0, practical_hours=0.5),
		]
		self.assertEqual(workload.row_hours(rows[0]), 6)
		self.assertEqual(workload.hours_by_faculty(rows), {"a": 10.5, "b": 2})  # a: 6 + 4.5

	def test_report_status(self):
		self.assertEqual(status_of(3, 4, 8, 2), "Under")
		self.assertEqual(status_of(4, 4, 8, 2), "Within")
		self.assertEqual(status_of(8, 4, 8, 2), "Within")
		self.assertEqual(status_of(9, 4, 8, 2), "Over")
		self.assertEqual(status_of(10.5, 4, 8, 2), "Beyond Limit")
		self.assertEqual(status_of(0, 0, 0, 0), "Within")  # teacher of a cadre without a norm


class AllocationFixture(CampusTestCase):
	demo_scale = "small"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		was_importing, frappe.flags.in_import = frappe.flags.in_import, True  # skip the users-per-minute throttle
		try:
			make_user(DEAN, [demo.ENGINEERING])
			make_user(ECE_HOD, [demo.ENGINEERING])
		finally:
			frappe.flags.in_import = was_importing
		frappe.get_doc("User", DEAN).add_roles("Dean Academics")
		cls.hold("DEAN-ACADEMICS", demo.ENGINEERING, DEAN)
		for user in (DEAN, ECE_HOD):
			frappe.db.set_value("User", user, "enabled", 1)  # import mode skipped the default
		frappe.get_doc("User", ECE_HOD).add_roles("HOD")
		cls.hold("HOD", ECE, ECE_HOD)
		cls.make_norm()
		cls.make_term_and_offerings()

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("wl_test")  # tests make documents of the same department and term

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="wl_test")
		super().tearDown()

	@staticmethod
	def hold(position, scope, user):
		if not frappe.db.exists("Position Holder", {"position": position, "scope_value": scope}):
			frappe.get_doc(
				{"doctype": "Position Holder", "position": position, "scope_value": scope, "user": user, "from_date": add_days(today(), -30)}
			).insert(ignore_permissions=True)

	@staticmethod
	def make_norm():
		hours = {"Professor": (1, 4, 8), "Associate Professor": (2, 5, 10), "Assistant Professor": (6, 6, 12)}
		frappe.get_doc(
			{
				"doctype": "Faculty Norm", "norm_name": "WL Test Norm", "company": demo.ENGINEERING, "effective_from": "2026-05-01",
				"student_faculty_ratio": 20, "overload_block_margin_hours": 2,
				"cadres": [
					{"cadre": cadre, "ratio_share": share, "min_hours_per_week": lo, "max_hours_per_week": hi}
					for cadre, (share, lo, hi) in hours.items()
				],
			}
		).insert(ignore_permissions=True)  # fmt: skip

	@classmethod
	def make_term_and_offerings(cls):
		year = demo.year_name(2026)
		frappe.get_doc(
			{"doctype": "Academic Term", "academic_year": year, "term_name": "WL Test Odd", "term_start_date": "2026-06-01", "term_end_date": "2026-11-30"}
		).insert()
		cls.term = frappe.db.get_value("Academic Term", {"academic_year": year, "term_name": "WL Test Odd"})
		cls.offerings = {}
		for key, department in (("O1", CSE), ("O2", CSE), ("O3", CSE), ("O4", CSE), ("O5", ECE)):
			program = demo.get_or_insert(
				"Program", {"program_name": f"WL Test {department[:3]}"}, {"oc_company": demo.ENGINEERING, "department": department}
			)
			course = demo.get_or_insert("Course", {"course_name": "Data Structures"}, {"oc_company": demo.ENGINEERING})
			cls.offerings[key] = frappe.get_doc(
				{
					"doctype": "Student Group", "student_group_name": f"WL Test {key}", "group_based_on": "Course",
					"academic_year": year, "academic_term": cls.term, "program": program, "course": course,
				}
			).insert().name  # fmt: skip

	def allocation(self, rows=BASE, department=CSE, **extra):
		return frappe.get_doc(
			{
				"doctype": "Course Allocation", "academic_term": self.term, "department": department,
				"allocations": [
					{"offering": self.offerings[o], "faculty": demo.employee_of(t), "lecture_hours": lec, "tutorial_hours": tut, "practical_hours": pra}
					for o, t, lec, tut, pra in rows
				],
				**extra,
			}
		)  # fmt: skip

	def submit_through_hod(self, doc):
		"""Request approval as the requester, then approve as the department's HOD."""
		request = request_approval(doc.doctype, doc.name)
		frappe.set_user(ECE_HOD if doc.department == ECE else demo.email(HOD))
		try:
			approve(request)
		finally:
			frappe.set_user("Administrator")
		doc.reload()

	def instructors(self, key):
		return set(frappe.get_all("Student Group Instructor", {"parent": self.offerings[key]}, pluck="instructor"))

	def instructor_of(self, username):
		return frappe.db.get_value("Instructor", {"employee": demo.employee_of(username)})


def over_limit_rows():
	"""Assistant B: 6 (O3) + 9 (O4) = 15 hours, past the maximum of 12 plus the margin of 2."""
	return [r for r in BASE if r[1] != ASSISTANT_B] + [("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 4, 1, 4)]


class TestWorkloadChecks(AllocationFixture):
	def test_hours_are_summed_per_row_and_the_company_comes_from_the_department(self):
		doc = self.allocation().insert()
		self.assertEqual([r.total_hours for r in doc.allocations], [3, 1, 5, 3, 6, 7])
		self.assertEqual(doc.company, demo.ENGINEERING)

	def test_over_the_maximum_warns_but_saves(self):
		frappe.clear_messages()
		doc = self.allocation().insert()  # Assistant B: 6 + 7 = 13 hours against a maximum of 12
		warnings = [m["message"] for m in frappe.get_message_log() if "maximum of" in m["message"]]
		self.assertEqual(len(warnings), 1)
		self.assertIn(demo.employee_of(ASSISTANT_B), warnings[0])
		self.assertIn("13.0 hours", warnings[0])
		self.assertFalse(doc.dean_override_by)

	def test_exactly_the_maximum_does_not_warn(self):
		frappe.clear_messages()
		rows = [r for r in BASE if r[1] != ASSISTANT_B] + [("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 3, 0, 3)]  # 6 + 6 = 12
		self.allocation(rows).insert()
		self.assertFalse([m for m in frappe.get_message_log() if "maximum of" in m["message"]])

	def test_max_plus_margin_itself_only_warns(self):
		rows = [r for r in BASE if r[1] != ASSISTANT_B] + [("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 4, 1, 3)]  # 6 + 8 = 14
		frappe.clear_messages()
		self.assertTrue(self.allocation(rows).insert().name)
		self.assertEqual(len([m for m in frappe.get_message_log() if "14.0 hours" in m["message"]]), 1)

	def test_over_the_maximum_plus_margin_is_blocked_without_a_dean_override(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.allocation(over_limit_rows()).insert()
		self.assertIn("15.0 hours", str(caught.exception))
		self.assertIn("Dean Academics", str(caught.exception))

	def test_hours_in_other_submitted_allocations_count(self):
		ece = self.allocation([("O5", ASSISTANT_B, 3, 0, 2)], department=ECE).insert()  # 5 hours in ECE
		self.submit_through_hod(ece)
		self.assertEqual(ece.docstatus, 1)
		rows = [r for r in BASE if r[1] != ASSISTANT_B] + [("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 2, 0, 0)]
		frappe.clear_messages()
		frappe.db.savepoint("first_draft")
		self.allocation(rows).insert()  # 6 + 2 in CSE alone is 8, but with the 5 in ECE it is 13
		self.assertEqual(len([m for m in frappe.get_message_log() if "13.0 hours" in m["message"]]), 1)
		frappe.db.rollback(save_point="first_draft")  # a second CSE draft would clash with the first
		rows[-1] = ("O4", ASSISTANT_B, 3, 0, 3)  # 5 + 6 + 6 = 17
		with self.assertRaises(frappe.ValidationError):
			self.allocation(rows).insert()


class TestDeanOverride(AllocationFixture):
	def test_only_the_dean_can_enter_the_override(self):
		with self.assertRaises(frappe.ValidationError):  # no reason
			self.allocation(over_limit_rows()).insert()
		with self.assertRaises(frappe.PermissionError):  # a reason, but not from the Dean
			self.allocation(over_limit_rows(), dean_override_reason="Visiting faculty left").insert()
		frappe.set_user(DEAN)
		try:
			doc = self.allocation(over_limit_rows(), dean_override_reason="Visiting faculty left").insert()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(doc.dean_override_by, DEAN)

	def test_override_survives_approval_but_not_a_change_to_the_rows(self):
		frappe.set_user(DEAN)
		try:
			doc = self.allocation(over_limit_rows(), dean_override_reason="Visiting faculty left").insert()
		finally:
			frappe.set_user("Administrator")
		doc.dean_override_by = "Administrator"  # a client cannot forge the approver
		doc.save()
		self.assertEqual(doc.dean_override_by, DEAN)
		doc.allocations[-1].practical_hours = 5  # a later edit by anyone but the Dean: 16 hours
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		doc.reload()
		self.submit_through_hod(doc)
		self.assertEqual(doc.docstatus, 1)

	def test_override_is_dropped_when_nothing_is_over_the_limit(self):
		doc = self.allocation(dean_override_reason="not needed").insert()
		self.assertFalse(doc.dean_override_reason or doc.dean_override_by)


class TestSubmission(AllocationFixture):
	def rows_without(self, key):
		return [r for r in BASE if r[0] != key]

	def test_an_offering_without_faculty_blocks_submit(self):
		frappe.clear_messages()
		doc = self.allocation(self.rows_without("O4")).insert()  # O4 has nobody
		self.assertTrue([m for m in frappe.get_message_log() if "still have no faculty" in m["message"] and self.offerings["O4"] in m["message"]])
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.submit()
		self.assertIn(self.offerings["O4"], str(caught.exception))
		self.assertNotIn(self.offerings["O1"], str(caught.exception))
		with self.assertRaises(frappe.ValidationError):
			self.submit_through_hod(doc)
		self.assertEqual(frappe.db.get_value("Course Allocation", doc.name, "docstatus"), 0)

	def test_every_offering_with_faculty_submits_after_hod_approval(self):
		doc = self.allocation().insert()
		with self.assertRaises(frappe.ValidationError):  # the approval policy forbids a direct submit
			doc.submit()
		request = request_approval(doc.doctype, doc.name)
		self.assertEqual(frappe.db.get_value("Approval Request", request, "status"), "Pending")
		self.assertEqual(frappe.db.get_value("Course Allocation", doc.name, "docstatus"), 0)
		frappe.set_user(demo.email(HOD))
		try:
			approve(request)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Course Allocation", doc.name, "docstatus"), 1)

	def test_instructors_follow_the_allocation_and_cancel_takes_them_off(self):
		group = frappe.get_doc("Student Group", self.offerings["O2"])
		for username in (ASSISTANT_A, ASSOCIATE):  # on O2 before the allocation; the Associate is allocated there too
			group.append("instructors", {"instructor": self.instructor_of(username)})
		group.save()
		doc = self.allocation().insert()
		self.submit_through_hod(doc)
		ins = self.instructor_of
		self.assertEqual(self.instructors("O1"), {ins(PROFESSOR), ins(ASSOCIATE)})
		self.assertEqual(self.instructors("O2"), {ins(ASSOCIATE), ins(ASSISTANT_A)})
		self.assertEqual(self.instructors("O3"), {ins(ASSISTANT_A), ins(ASSISTANT_B)})
		self.assertEqual(self.instructors("O4"), {ins(ASSISTANT_B)})
		doc.cancel()
		self.assertEqual([self.instructors(k) for k in ("O1", "O2", "O3", "O4")], [set(), {ins(ASSISTANT_A), ins(ASSOCIATE)}, set(), set()])

	def test_row_checks(self):
		duplicate_pair = BASE + [("O1", PROFESSOR, 1, 0, 0)]
		for rows, text in (
			(duplicate_pair, "already allocated"),
			(BASE + [("O5", PROFESSOR, 1, 0, 0)], "not a course offering"),
			(BASE + [("O1", "principal", 1, 0, 0)], "no Instructor"),
			(BASE + [("O1", ASSISTANT_A, 0, 0, 0)], "weekly Lecture"),
		):
			with self.assertRaises(frappe.ValidationError) as caught:
				self.allocation(rows).insert()
			self.assertIn(text, str(caught.exception))

	def test_one_live_allocation_per_department_and_term(self):
		first = self.allocation().insert()
		with self.assertRaises(frappe.ValidationError):
			self.allocation().insert()
		self.assertEqual(self.allocation(department=ECE, rows=[("O5", PROFESSOR, 2, 0, 0)]).insert().department, ECE)
		self.assertTrue(first.name)


class TestWorkloadBalanceReport(AllocationFixture):
	def run_report(self, **filters):
		return balance_report({"company": demo.ENGINEERING, "academic_term": self.term, **filters})

	def test_figures_follow_the_submitted_allocation(self):
		_columns, rows, *_rest = self.run_report()
		self.assertEqual({r["total"] for r in rows if "faculty" in r}, {0})  # a draft counts for nothing
		self.submit_through_hod(self.allocation().insert())
		_columns, rows, _message, _chart, summary = self.run_report()
		by_teacher = {r["faculty"]: r for r in rows if r.get("faculty")}
		expected = {  # employee: lecture, tutorial, practical, total, min, max, status
			PROFESSOR: (3, 0, 0, 3, 4, 8, "Under"),
			ASSOCIATE: (3, 1, 2, 6, 5, 10, "Within"),
			ASSISTANT_A: (3, 0, 0, 3, 6, 12, "Under"),
			ASSISTANT_B: (7, 1, 5, 13, 6, 12, "Over"),
		}
		for username, values in expected.items():
			row = by_teacher[demo.employee_of(username)]
			self.assertEqual((row["lecture"], row["tutorial"], row["practical"], row["total"], row["minimum"], row["maximum"], row["status"]), values)
		total = next(r for r in rows if r.get("bold") and r["department"] == CSE)
		self.assertEqual((total["lecture"], total["tutorial"], total["practical"], total["total"]), (16, 2, 7, 25))
		figures = {s["label"]: s["value"] for s in summary}
		self.assertEqual((figures["Teachers"], figures["Total Weekly Hours"], figures["Under Minimum"], figures["Over Maximum"]), (4, 25, 2, 1))

	def test_a_cancelled_allocation_drops_out(self):
		doc = self.allocation().insert()
		self.submit_through_hod(doc)
		doc.cancel()
		_columns, rows, *_rest = self.run_report()
		self.assertEqual({r["total"] for r in rows if r.get("faculty")}, {0})

	def test_department_filter_and_company_scope(self):
		_columns, rows, *_rest = self.run_report(department=ECE)
		self.assertEqual(rows, [])  # no teaching staff in ECE
		frappe.set_user(DEAN)
		try:
			self.assertEqual(self.run_report(company=demo.ARTS)[1], [])
		finally:
			frappe.set_user("Administrator")


class TestFixRound1(AllocationFixture):
	def test_request_is_refused_while_offerings_have_no_faculty(self):
		doc = self.allocation([r for r in BASE if r[0] != "O4"]).insert()
		with self.assertRaises(frappe.ValidationError):
			request_approval(doc.doctype, doc.name)
		self.assertIsNone(latest_request(doc))

	def test_request_is_refused_past_the_block_margin_without_a_dean_override(self):
		frappe.set_user(DEAN)
		try:
			doc = self.allocation(over_limit_rows(), dean_override_reason="Visiting faculty left").insert()
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(request_approval(doc.doctype, doc.name))  # the Dean's override carries into the request
		frappe.db.set_value("Course Allocation", doc.name, "dean_override_by", None)
		frappe.db.delete("Approval Request", {"reference_name": doc.name})
		with self.assertRaises(frappe.PermissionError):
			request_approval(doc.doctype, doc.name)

	def test_policy_is_seeded_idempotently_and_only_the_departments_hod_approves(self):
		frappe.db.delete("Approval Level", {"parenttype": "Approval Policy", "parent": "Course Allocation - HOD"})
		frappe.db.delete("Approval Policy", {"document_type": "Course Allocation"})
		seed_course_allocation_policy()
		seed_course_allocation_policy()
		self.assertEqual(frappe.get_all("Approval Policy", {"document_type": "Course Allocation"}, pluck="name"), ["Course Allocation - HOD"])
		doc = self.allocation().insert()
		request = request_approval(doc.doctype, doc.name)
		for user in (ECE_HOD, DEAN):  # the HOD of another department and a stranger
			frappe.set_user(user)
			try:
				with self.assertRaises(frappe.PermissionError):
					approve(request)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Course Allocation", doc.name, "docstatus"), 0)

	def test_faculty_of_another_company_is_refused(self):
		frappe.db.set_value("Employee", demo.employee_of(ASSISTANT_A), "company", demo.ARTS)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.allocation().insert()
		self.assertIn(demo.ARTS, str(caught.exception))

	def test_offering_of_another_company_is_refused(self):
		frappe.db.set_value("Program", frappe.db.get_value("Student Group", self.offerings["O1"], "program"), "oc_company", demo.ARTS)
		with self.assertRaises(frappe.ValidationError):
			self.allocation().insert()

	def test_submitted_hours_are_per_company(self):
		self.submit_through_hod(self.allocation().insert())
		b = demo.employee_of(ASSISTANT_B)
		self.assertEqual(workload.submitted_hours(self.term, demo.ENGINEERING)[b], 13)
		self.assertEqual(workload.submitted_hours(self.term, demo.ARTS), {})

	def test_no_cadre_and_no_maximum_warn_instead_of_passing_silently(self):
		frappe.db.set_value("Employee", demo.employee_of(ASSISTANT_A), "oc_cadre", None)
		frappe.db.set_value("Faculty Norm Cadre", {"parent": ["like", "%"], "cadre": "Associate Professor", "min_hours_per_week": 5}, "max_hours_per_week", 0)
		frappe.clear_messages()
		self.allocation().insert()
		texts = [m["message"] for m in frappe.get_message_log()]
		self.assertTrue([t for t in texts if demo.employee_of(ASSISTANT_A) in t and "no cadre" in t])
		self.assertTrue([t for t in texts if demo.employee_of(ASSOCIATE) in t and "no maximum" in t])

	def test_submit_rechecks_hours_other_allocations_added_since_the_draft(self):
		mine = self.allocation([r for r in BASE if r[1] != ASSISTANT_B] + [("O3", ASSISTANT_B, 3, 0, 3), ("O4", ASSISTANT_B, 2, 0, 0)]).insert()  # 8 hours
		ece = self.allocation([("O5", ASSISTANT_B, 4, 1, 4)], department=ECE).insert()  # 9 hours
		self.submit_through_hod(ece)
		with self.assertRaises(frappe.ValidationError):  # 9 + 8 = 17
			self.submit_through_hod(mine)
		self.assertEqual(frappe.db.get_value("Course Allocation", mine.name, "docstatus"), 0)
