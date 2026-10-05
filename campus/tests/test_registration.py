"""P1-T13 integration tests (M03-04): offerings, Course Registration rules, approval to enrollment, report."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from campus.campus_platform.approvals import approve, request_approval
from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.curriculum.api import generate_offerings
from campus.curriculum.report.elective_enrolment.elective_enrolment import execute as elective_report
from campus.tests import approval_fixtures as fx
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import enroll, make_program, make_regulation, make_student, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Registration Test College"
OTHER_COLLEGE = "Registration Other College"
ABBR = "RGT"
PROGRAM = "Registration Test BE"
POLICY = "REG Test Class Advisor then HOD"
ADVISOR = "reg-advisor@example.com"
HOD = "reg-hod@example.com"
OPENS, CLOSES = "2022-06-01", "2022-06-20"
IN_WINDOW = "2022-06-10"  # day 9 of a term starting 2022-06-01
AFTER_DROP = "2022-07-15"  # past start + 30 days
TERM_ODD, TERM_EVEN = "Reg Odd", "Reg Even"

# course -> (semester, credits, elective group). Credits are fixed per row (override) for clear arithmetic.
COURSES = {
	"REG A": (5, 18, None), "REG B": (5, 18, None), "REG C": (5, 3, None), "REG D": (5, 3, None),
	"REG E": (3, 4, None),  # arrear course of an earlier odd semester
	"REG D1": (5, 4, None), "REG D2": (5, 3, None),
	"REG AD1": (5, 4, None), "REG AD2": (5, 4, None), "REG AD3": (5, 2, None), "REG AD4": (5, 2, None),
	"REG AD5": (5, 2, None),
	"REG EL1": (5, 3, "G1"), "REG EL2": (5, 3, "G1"), "REG EL3": (5, 3, "G1"), "REG EL4": (5, 3, "G2"),
	"REG S4": (4, 3, None),  # an even-semester course
}
STUDENTS = [f"Regs{n}" for n in range(1, 7)]


def clear_previous_run():
	registrations = frappe.get_all("Course Registration", {"company": COLLEGE}, pluck="name") or [""]
	requests = frappe.get_all(
		"Approval Request", {"reference_doctype": "Course Registration", "reference_name": ["in", registrations]}, pluck="name"
	) or [""]
	for child in ("Approval Request Approver", "Approval Action"):
		frappe.db.delete(child, {"parent": ["in", requests]})
	frappe.db.delete("Approval Request", {"name": ["in", requests]})
	frappe.db.delete("Course Registration Item", {"parent": ["in", registrations]})
	frappe.db.delete("Course Registration", {"name": ["in", registrations]})
	frappe.db.delete("Notification Log", {"document_type": "Course Registration"})
	students = frappe.get_all("Student", {"oc_company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Course Enrollment", {"student": ["in", students]})
	offerings = frappe.get_all("Student Group", {"oc_company": COLLEGE, "group_based_on": "Course"}, pluck="name") or [""]
	frappe.db.delete("Student Group Student", {"parent": ["in", offerings]})
	frappe.db.delete("Registration Window", {"company": COLLEGE})


def clear_world():
	clear_previous_run()
	groups = frappe.get_all("Student Group", {"oc_company": COLLEGE}, pluck="name") or [""]
	frappe.db.delete("Student Group Student", {"parent": ["in", groups]})
	frappe.db.delete("Student Group", {"name": ["in", groups]})
	frappe.db.delete("Elective Group", {"curriculum": ["like", f"{ABBR}-%"]})
	for name in frappe.get_all("Curriculum", {"program": PROGRAM}, pluck="name"):
		frappe.db.delete("Curriculum Course", {"parent": name})
		frappe.db.delete("Category Credit Requirement", {"parent": name})
		frappe.db.delete("Curriculum", {"name": name})
	frappe.db.delete("Registration Rule")
	frappe.db.delete("Curriculum Rule", {"regulation": ["like", "%-RGC"]})


def make_term(term_name, start, end):
	existing = frappe.db.get_value("Academic Term", {"academic_year": year_name("2022"), "term_name": term_name})
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Academic Term", "academic_year": year_name("2022"), "term_name": term_name,
			"term_start_date": start, "term_end_date": end,
		}
	).insert().name  # fmt: skip


def make_course(name):
	if not frappe.db.exists("Course", name):
		frappe.get_doc({"doctype": "Course", "course_name": name, "oc_company": COLLEGE}).insert()


def make_curriculum(regulation):
	rows = [
		{
			"semester": semester, "course": course, "category": "PEC" if group else "PCC", "lecture_periods": 3,
			"credits_override": 1, "credits": credits, "is_elective": 1 if group else 0,
		}
		for course, (semester, credits, group) in COURSES.items()
	]  # fmt: skip
	doc = frappe.get_doc(
		{"doctype": "Curriculum", "program": PROGRAM, "regulation": regulation, "status": "Draft", "courses": rows}
	).insert()
	groups = {}
	for key, cap, choose in (("G1", 1, 2), ("G2", 0, 1)):
		groups[key] = frappe.get_doc(
			{
				"doctype": "Elective Group", "curriculum": doc.name, "semester": 5, "group_name": key,
				"choose_n": choose, "seat_cap_per_course": cap,
			}
		).insert().name  # fmt: skip
	for row in doc.courses:
		row.elective_group = groups.get(COURSES[row.course][2])
	doc.save()
	doc.status = "Approved"
	doc.save()
	doc.status = "Effective"
	doc.save()
	return doc, groups


class RegistrationTestCase(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		clear_world()
		make_company(COLLEGE, "RGTC")
		make_company(OTHER_COLLEGE, "RGOC")
		make_year("2022")
		program = make_program(PROGRAM, COLLEGE)
		frappe.db.set_value("Program", program, {"program_abbreviation": ABBR, "oc_total_semesters": 8})
		cls.regulation = make_regulation("R2022", COLLEGE, [PROGRAM], "2022").name
		frappe.get_doc(
			{
				"doctype": "Curriculum Rule", "regulation": cls.regulation, "lecture_credit_per_period": 1,
				"tutorial_credit_per_period": 1, "practical_credit_per_period": 0.5,
			}
		).insert()  # fmt: skip
		cls.rule = frappe.get_doc(
			{
				"doctype": "Registration Rule", "regulation": cls.regulation, "max_credits_per_semester": 36,
				"excluded_types": "Arrear\nDropped", "max_credits_clause": "6.1", "max_drop_credits": 6,
				"drop_window_days": 30, "drop_clause": "6.2", "add_from_semester": 5, "max_add_credits": 6,
				"max_add_courses": 2, "add_clause": "6.3", "elective_min_enrolment": 10, "elective_clause": "6.4",
			}
		).insert()  # fmt: skip
		for course in COURSES:
			make_course(course)
		cls.odd = make_term(TERM_ODD, OPENS, "2022-11-30")
		cls.even = make_term(TERM_EVEN, "2023-01-01", "2023-05-31")
		cls.curriculum, cls.groups = make_curriculum(cls.regulation)
		cls.students = [make_student(name, COLLEGE, "2022") for name in STUDENTS]
		for student in cls.students:
			enroll(student, PROGRAM, "2022")
		generate_offerings(cls.curriculum.name, cls.odd, "A,B")

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		clear_previous_run()
		self.window = self.make_window()

	def make_window(self, opens=OPENS, closes=CLOSES, **extra):
		return frappe.get_doc(
			{
				"doctype": "Registration Window", "company": COLLEGE, "academic_term": self.odd,
				"opens_on": opens, "closes_on": closes, **extra,
			}
		).insert()  # fmt: skip

	def registration(self, rows, student=0, semester=5, date=IN_WINDOW, term=None, **extra):
		"""Insert (not submit) a Course Registration; `rows` are (course, type) pairs."""
		return frappe.get_doc(
			{
				"doctype": "Course Registration", "student": self.students[student].name, "semester": semester,
				"academic_term": term or self.odd, "registration_date": date,
				"items": [{"course": c, "registration_type": t} for c, t in rows], **extra,
			}
		).insert()  # fmt: skip

	def regular(self, *courses, **kwargs):
		return self.registration([(c, "Regular") for c in courses], **kwargs)

	def assert_rejected(self, rows, pattern, **kwargs):
		with self.assertRaisesRegex(frappe.ValidationError, pattern):
			self.registration(rows, **kwargs)

	def members(self, student, course):
		return frappe.db.sql(
			"""select count(*) from `tabStudent Group Student` m join `tabStudent Group` g on g.name = m.parent
			where m.student = %s and g.course = %s and g.academic_term = %s""",
			(self.students[student].name, course, self.odd),
		)[0][0]

	def enrollments(self, student, course):
		return frappe.db.count("Course Enrollment", {"student": self.students[student].name, "course": course})


class TestOfferingsAndRecords(RegistrationTestCase):
	def test_student_group_custom_fields_exist(self):
		for fieldname in ("oc_curriculum", "oc_semester", "oc_section", "oc_course_category"):
			self.assertTrue(frappe.get_meta("Student Group").has_field(fieldname), fieldname)

	def test_generator_creates_odd_semester_courses_per_section(self):
		groups = frappe.get_all(
			"Student Group", {"oc_curriculum": self.curriculum.name, "academic_term": self.odd},
			["name", "course", "oc_semester", "oc_section", "oc_course_category", "group_based_on", "oc_company"],
		)  # fmt: skip
		odd_courses = [c for c, (sem, _credits, _g) in COURSES.items() if sem % 2]
		self.assertEqual(len(groups), len(odd_courses) * 2)
		self.assertNotIn("REG S4", {g.course for g in groups})
		sample = next(g for g in groups if g.course == "REG A" and g.oc_section == "B")
		self.assertEqual(sample.name, f"REG A-{self.odd}-B")
		self.assertEqual((sample.group_based_on, sample.oc_semester, sample.oc_course_category), ("Course", 5, "PCC"))
		self.assertEqual(sample.oc_company, COLLEGE)

	def test_generator_is_idempotent(self):
		before = frappe.db.count("Student Group", {"oc_curriculum": self.curriculum.name, "academic_term": self.odd})
		result = generate_offerings(self.curriculum.name, self.odd, ["A", "B"])
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["existing"]), before)
		self.assertEqual(frappe.db.count("Student Group", {"oc_curriculum": self.curriculum.name, "academic_term": self.odd}), before)

	def test_explicit_semester_parity_on_the_term_overrides_the_name(self):
		self.assertTrue(frappe.get_meta("Academic Term").has_field("oc_semester_parity"))
		frappe.db.set_value("Academic Term", self.even, "oc_semester_parity", "Odd")
		self.addCleanup(frappe.db.set_value, "Academic Term", self.even, "oc_semester_parity", None)
		result = generate_offerings(self.curriculum.name, self.even, "A")
		self.assertIn(f"REG A-{self.even}-A", result["created"])
		self.assertNotIn(f"REG S4-{self.even}-A", result["created"])

	def test_even_term_offers_even_semester_courses(self):
		result = generate_offerings(self.curriculum.name, self.even, "A")
		self.assertEqual(result["created"], [f"REG S4-{self.even}-A"])

	def test_generator_refuses_a_draft_curriculum(self):
		draft = frappe.get_doc({"doctype": "Curriculum", "program": PROGRAM, "regulation": self.regulation, "version": 2, "courses": [{"semester": 1, "course": "REG C", "category": "PCC", "lecture_periods": 3}]})
		draft.insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Approved or Effective"):
			generate_offerings(draft.name, self.odd, "A")

	def test_elective_offering_carries_the_seat_cap_as_max_strength(self):
		self.assertEqual(frappe.db.get_value("Student Group", f"REG EL1-{self.odd}-A", "max_strength"), 1)
		self.assertEqual(frappe.db.get_value("Student Group", f"REG A-{self.odd}-A", "max_strength"), 0)

	def test_rule_rejects_unknown_excluded_type(self):
		self.rule.excluded_types = "Arrear\nWithdrawn"
		with self.assertRaisesRegex(frappe.ValidationError, "Withdrawn"):
			self.rule.save()
		self.rule.reload()

	def test_window_must_close_after_it_opens_and_is_unique_per_term(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be before"):
			self.make_window(opens="2022-06-10", closes="2022-06-01")
		with self.assertRaisesRegex(frappe.ValidationError, "already covers"):
			self.make_window()


class TestRegistrationRules(RegistrationTestCase):
	def test_credits_come_from_the_effective_curriculum(self):
		doc = self.regular("REG A", "REG C")
		self.assertEqual([i.credits for i in doc.items], [18, 3])
		self.assertEqual(doc.total_credits, 21)
		self.assertEqual((doc.curriculum, doc.regulation, doc.company), (self.curriculum.name, self.regulation, COLLEGE))

	def test_course_outside_the_curriculum_is_rejected(self):
		make_course("REG X")
		self.assert_rejected([("REG X", "Regular")], "not in curriculum")

	def test_over_36_credits_is_rejected_with_the_clause(self):
		self.assert_rejected([("REG A", "Regular"), ("REG B", "Regular"), ("REG C", "Regular")], r"R2022 cl\. 6\.1: 39 credits registered; the maximum is 36")

	def test_exactly_36_credits_is_accepted(self):
		self.assertEqual(self.regular("REG A", "REG B").total_credits, 36)

	def test_arrear_credits_are_excluded_from_the_36(self):
		doc = self.registration([("REG A", "Regular"), ("REG B", "Regular"), ("REG E", "Arrear")])
		self.assertEqual(doc.total_credits, 36)

	def test_window_may_override_the_maximum_credits(self):
		self.window.db_set("max_credits", 20)
		self.assert_rejected([("REG A", "Regular"), ("REG C", "Regular")], r"the maximum is 20")

	def test_registration_outside_the_window_is_rejected(self):
		self.assert_rejected([("REG C", "Regular")], "not open", date="2022-06-21")

	def test_registration_without_a_window_is_rejected(self):
		self.window.delete()
		self.assert_rejected([("REG C", "Regular")], "not open")

	def test_duplicate_course_in_one_registration_is_rejected(self):
		self.assert_rejected([("REG C", "Regular"), ("REG C", "Regular")], "listed twice")

	def test_prerequisite_check_is_called_for_courses_that_have_prerequisites(self):
		frappe.db.set_value("Curriculum Course", {"parent": self.curriculum.name, "course": "REG C"}, "prerequisites", "REG D")
		with patch("campus.curriculum.doctype.course_registration.course_registration.prerequisites_met", return_value=False) as check:
			self.assert_rejected([("REG C", "Regular")], "prerequisites of .*REG C.* are not met")
		check.assert_called_once_with(self.students[0].name, "REG C")
		self.regular("REG C")  # the Phase 1 stub returns True
		frappe.db.set_value("Curriculum Course", {"parent": self.curriculum.name, "course": "REG C"}, "prerequisites", None)

	def test_additional_courses_not_allowed_before_semester_five(self):
		self.assert_rejected([("REG AD3", "Additional")], r"R2022 cl\. 6\.3: additional courses are allowed from semester 5", semester=4)

	def test_additional_credits_over_six_rejected(self):
		self.assert_rejected([("REG AD1", "Additional"), ("REG AD2", "Additional")], r"8 additional credits; at most 6")

	def test_three_additional_courses_rejected_two_accepted(self):
		self.assert_rejected(
			[("REG AD3", "Additional"), ("REG AD4", "Additional"), ("REG AD5", "Additional")], r"3 additional courses; at most 2"
		)
		self.registration([("REG AD3", "Additional"), ("REG AD4", "Additional")])

	def test_choose_n_counts_electives_held_from_earlier_registrations(self):
		self.regular("REG EL1", "REG EL2").submit()  # fills choose-2 of G1 for student 0 (EL1 cap 1 is theirs)
		self.assert_rejected([("REG EL3", "Regular")], r"allows 2 course\(s\); 3 chosen")

	def test_regular_course_of_another_semester_is_rejected_but_arrear_is_fine(self):
		self.assert_rejected([("REG E", "Regular")], r"not a semester 5 course.*register it as Arrear")
		self.assertEqual(self.registration([("REG E", "Arrear")]).items[0].semester, 3)

	def test_elective_group_choose_n_is_enforced(self):
		self.assert_rejected([(c, "Regular") for c in ("REG EL1", "REG EL2", "REG EL3")], r"allows 2 course\(s\); 3 chosen")


class TestDrops(RegistrationTestCase):
	def setUp(self):
		super().setUp()
		reg = self.regular("REG D1", "REG D2")
		reg.submit()  # no policy yet: submits directly and enrolls

	def test_dropping_seven_credits_is_rejected(self):
		self.assert_rejected([("REG D1", "Dropped"), ("REG D2", "Dropped")], r"R2022 cl\. 6\.2: 7 credits dropped; at most 6")

	def test_dropping_after_thirty_days_is_rejected(self):
		self.assert_rejected([("REG D2", "Dropped")], r"only until 2022-07-01", date=AFTER_DROP)

	def test_window_drop_until_overrides_the_thirty_days(self):
		self.window.db_set("drop_until", "2022-08-01")
		self.registration([("REG D2", "Dropped")], date=AFTER_DROP)

	def test_dropping_within_limits_removes_the_seat_on_submit(self):
		self.assertEqual(self.members(0, "REG D1"), 1)
		drop = self.registration([("REG D1", "Dropped")], date="2022-06-25")  # window closed, drop allowed
		drop.submit()
		self.assertEqual(self.members(0, "REG D1"), 0)
		self.assertEqual(self.enrollments(0, "REG D1"), 0)
		self.assertEqual(self.members(0, "REG D2"), 1)

	def test_dropping_an_unregistered_course_is_rejected(self):
		self.assert_rejected([("REG C", "Dropped")], "not registered this term")

	def test_registering_an_already_registered_course_is_rejected(self):
		self.assert_rejected([("REG D1", "Regular")], "already registered this term")


class TestSeatCap(RegistrationTestCase):
	def test_elective_at_its_seat_cap_rejects_new_registrations(self):
		self.regular("REG EL1", student=0).submit()
		self.assert_rejected([("REG EL1", "Regular")], r"R2022 cl\. 6\.4: elective REG EL1 is full: all 1 seats", student=1)

	def test_last_seat_goes_to_the_first_submit_and_the_second_fails(self):
		"""Both drafts pass the unlocked draft check while a seat is free. Submit then takes the Elective
		Group row FOR UPDATE and recounts membership, so of two concurrent submits the second blocks on the
		lock and sees the winner's membership; here the two submits run one after the other, which is the
		order the lock forces."""
		first = self.regular("REG EL1", student=0)
		second = self.regular("REG EL1", student=1)
		first.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "is full"):
			second.submit()
		self.assertEqual(self.members(0, "REG EL1"), 1)
		self.assertEqual(self.members(1, "REG EL1"), 0)
		self.assertEqual(frappe.db.get_value("Course Registration", second.name, "docstatus"), 0)

	def test_uncapped_elective_group_accepts_everyone(self):
		for student in range(3):
			self.regular("REG EL4", student=student).submit()
		self.assertEqual(sum(self.members(s, "REG EL4") for s in range(3)), 3)

	def test_submit_takes_the_row_lock_on_the_elective_group(self):
		doc = self.regular("REG EL1", student=0)
		with patch("frappe.db.get_value", wraps=frappe.db.get_value) as get_value:
			doc.submit()
		locked = [c for c in get_value.call_args_list if c.kwargs.get("for_update") and c.args[0] == "Elective Group"]
		self.assertTrue(locked)

	def test_post_lock_seat_count_is_a_locking_read(self):
		"""After the Elective Group lock the membership count must be `... FOR UPDATE`: a plain SELECT would
		read the transaction's stale REPEATABLE READ snapshot and let two concurrent submits both pass.
		(A real two-connection test is not possible: the test world is uncommitted, so a second
		connection cannot see it.)"""
		doc = self.regular("REG EL1", student=0)
		with patch("frappe.db.sql", wraps=frappe.db.sql) as sql:
			doc.submit()
		counts = [str(c.args[0]) for c in sql.call_args_list if "tabStudent Group Student" in str(c.args[0]) and "COUNT" not in str(c.args[0]).upper() and str(c.args[0]).lstrip().upper().startswith("SELECT")]
		locking = [q for q in counts if q.rstrip().upper().endswith("FOR UPDATE")]
		self.assertTrue(locking, counts)


class TestPermissions(RegistrationTestCase):
	def user(self, email, companies, role):
		make_user(email, companies)  # gives Academics User
		doc = frappe.get_doc("User", email)
		doc.add_roles(role)
		if role == "Student":
			doc.remove_roles("Academics User")
		return email

	def test_user_restricted_to_another_company_cannot_register_a_student(self):
		outsider = self.user("reg-outsider2@example.com", [OTHER_COLLEGE], "Academics User")
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			self.regular("REG C")

	def test_user_restricted_to_another_company_cannot_submit(self):
		doc = self.regular("REG C")
		frappe.set_user(self.user("reg-outsider3@example.com", [OTHER_COLLEGE], "Academics User"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Course Registration", doc.name).submit()

	def test_user_of_the_same_company_can_register(self):
		frappe.set_user(self.user("reg-insider@example.com", [COLLEGE], "Academics User"))
		self.assertEqual(self.regular("REG C").docstatus, 0)

	def test_offering_of_another_company_is_rejected(self):
		group = f"REG C-{self.odd}-A"
		frappe.db.set_value("Student Group", group, "oc_company", OTHER_COLLEGE)
		self.addCleanup(frappe.db.set_value, "Student Group", group, "oc_company", COLLEGE)
		with self.assertRaisesRegex(frappe.ValidationError, "another company"):
			self.regular("REG C").submit()

	def test_student_role_user_cannot_register_anyone(self):
		frappe.set_user(self.user("reg-student@example.com", [COLLEGE], "Student"))
		with self.assertRaises(frappe.PermissionError):
			self.regular("REG C", student=1)


class TestApprovalAndEnrollment(RegistrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		fx.setup_world()
		department = fx.make_department("Registration Test CSE", COLLEGE)
		frappe.db.set_value("Program", PROGRAM, "department", department)
		cls.department = department
		for user in (ADVISOR, HOD):
			make_user(user, [COLLEGE])
		cls.group = frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": "REG Class Group", "group_based_on": "Batch",
				"academic_year": year_name("2022"), "program": PROGRAM, "oc_section": "B",
				"students": [{"student": cls.students[0].name}],
			}
		).insert().name  # fmt: skip
		for code, user, scope in (("CLASS-ADVISOR", ADVISOR, cls.group), ("HOD", HOD, department)):
			if not frappe.db.exists("Position Holder", {"position": code, "scope_value": scope}):
				frappe.get_doc(
					{
						"doctype": "Position Holder", "position": code, "scope_value": scope, "user": user,
						"from_date": add_days(getdate(), -30),
					}
				).insert()  # fmt: skip

	def setUp(self):
		super().setUp()
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})
		self.policy = frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": POLICY, "document_type": "Course Registration",
				"company": COLLEGE,
				"levels": [
					fx.level("Position", "CLASS-ADVISOR", title="Class Advisor", scope_field="class_group"),
					fx.level("Position", "HOD", title="HOD", scope_field="department"),
				],
			}
		).insert()  # fmt: skip
		self.addCleanup(self.drop_policy)

	def drop_policy(self):
		frappe.db.delete("Approval Level", {"parent": POLICY})
		frappe.db.delete("Approval Policy", {"name": POLICY})

	def act(self, user, request):
		frappe.set_user(user)
		try:
			return approve(request, None)
		finally:
			frappe.set_user("Administrator")

	def approved_registration(self, *courses):
		doc = self.regular(*courses)
		request = request_approval("Course Registration", doc.name)
		self.assertEqual(self.act(ADVISOR, request), "Pending")
		self.assertEqual(frappe.db.get_value("Course Registration", doc.name, "docstatus"), 0)
		self.assertEqual(self.act(HOD, request), "Approved")
		doc.reload()
		return doc

	def test_class_group_and_department_scope_the_approval(self):
		doc = self.regular("REG C")
		self.assertEqual((doc.class_group, doc.department), (self.group, self.department))

	def test_direct_submit_is_blocked_by_the_policy(self):
		doc = self.regular("REG C")
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			doc.submit()

	def test_final_approval_enrolls_the_student_exactly_once(self):
		doc = self.approved_registration("REG C", "REG D")
		self.assertEqual(doc.docstatus, 1)
		for course in ("REG C", "REG D"):
			self.assertEqual(self.members(0, course), 1)
			self.assertEqual(self.enrollments(0, course), 1)
		self.assertEqual([i.offering for i in doc.items], [f"REG C-{self.odd}-B", f"REG D-{self.odd}-B"])  # class section B

	def test_applying_the_enrollment_again_adds_nothing(self):
		doc = self.approved_registration("REG C")
		doc.apply_rows(enrolling=True)
		doc.apply_rows(enrolling=True)
		self.assertEqual(self.members(0, "REG C"), 1)
		self.assertEqual(self.enrollments(0, "REG C"), 1)
		group = frappe.get_doc("Student Group", f"REG C-{self.odd}-B")
		self.assertEqual([s.student for s in group.students].count(self.students[0].name), 1)

	def test_course_enrollment_belongs_to_the_students_program_enrollment(self):
		self.approved_registration("REG C")
		enrollment = frappe.get_doc("Course Enrollment", {"student": self.students[0].name, "course": "REG C"})
		self.assertEqual(frappe.db.get_value("Program Enrollment", enrollment.program_enrollment, "student"), self.students[0].name)

	def test_cancelling_reverses_the_enrollment(self):
		doc = self.approved_registration("REG C")
		doc.cancel()
		self.assertEqual(self.members(0, "REG C"), 0)
		self.assertEqual(self.enrollments(0, "REG C"), 0)


class TestElectiveReport(RegistrationTestCase):
	def run_report(self, **filters):
		_columns, rows = elective_report({"company": COLLEGE, "academic_term": self.odd, **filters})
		return {r["course"]: r for r in rows}

	def test_lists_each_elective_with_cap_enrolment_and_minimum(self):
		self.regular("REG EL1", student=0).submit()
		rows = self.run_report()
		self.assertEqual(set(rows), {"REG EL1", "REG EL2", "REG EL3", "REG EL4"})
		self.assertEqual(
			(rows["REG EL1"]["seat_cap"], rows["REG EL1"]["enrolled"], rows["REG EL1"]["minimum"], rows["REG EL1"]["offerings"]),
			(1, 1, 10, 2),
		)

	def test_below_minimum_is_flagged_only_after_the_window_closes(self):
		self.regular("REG EL4", student=0).submit()
		with patch("campus.curriculum.report.elective_enrolment.elective_enrolment.today", return_value="2022-06-15"):
			row = self.run_report()["REG EL4"]
		self.assertEqual((row["status"], row["below_minimum"]), ("Filling", 0))
		row = self.run_report()["REG EL4"]  # the real today is long after CLOSES
		self.assertEqual((row["status"], row["below_minimum"]), ("Below Minimum", 1))

	def test_report_is_scoped_to_the_company(self):
		self.assertEqual(self.run_report(company=OTHER_COLLEGE), {})

	def test_report_respects_user_permissions_on_company(self):
		make_user("reg-outsider@example.com", [OTHER_COLLEGE])
		frappe.set_user("reg-outsider@example.com")
		self.assertEqual(self.run_report(), {})
