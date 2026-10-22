"""P1-T18 tests (M05-01, M05-07): student fields, student onboarding, mentor allocation and visibility, ID card."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.verification import verify
from campus.student_services import api, onboarding
from campus.student_services.doctype.student_onboarding.student_onboarding import completion_percent
from campus.tests.test_admission_flow import COLLEGE, OC, OTHER_COLLEGE, PROGRAM, QUOTA, YEAR, AdmitTestCase

HOD, DEAN, PLAIN_USER = "t18-hod@example.com", "t18-dean@example.com", "t18-plain@example.com"
MENTORS = [f"t18-mentor{n}@example.com" for n in (1, 2, 3)]
SERIAL = [0]


def make_role_user(email, *roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert()
	frappe.get_doc("User", email).add_roles(*roles)
	for company in (COLLEGE,):
		if not frappe.db.exists("User Permission", {"user": email, "allow": "Company", "for_value": company}):
			frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company}).insert()


def make_employee(user):
	existing = frappe.db.get_value("Employee", {"user_id": user})
	if existing:
		return existing
	if not frappe.db.exists("Gender", "Female"):
		frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
	return frappe.get_doc(
		{
			"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": user.split("@")[0], "gender": "Female",
			"date_of_birth": "1980-01-01", "date_of_joining": "2015-06-01", "status": "Active", "company": COLLEGE,
			"user_id": user, "create_user_permission": 0,
		}
	).insert().name


def make_userless_employee(company):
	return frappe.get_doc(
		{"doctype": "Employee", "naming_series": "HR-EMP-", "first_name": "T18 Userless", "gender": "Female",
		"date_of_birth": "1980-01-01", "date_of_joining": "2015-06-01", "status": "Active", "company": company,
		"create_user_permission": 0}
	).insert().name


def make_foreign_mentor():
	"""An active MENTOR position holder employed by the other college."""
	user = "t18-foreign-mentor@example.com"
	make_role_user(user)
	employee = make_employee(user)
	frappe.db.set_value("Employee", employee, "company", OTHER_COLLEGE)
	group = frappe.db.get_value("Student Group", {"student_group_name": "T18 Mentor Scope"})
	frappe.get_doc(
		{"doctype": "Position Holder", "position": "MENTOR", "user": user, "scope_value": group,
		"from_date": add_days(today(), -30)}
	).insert()
	return employee


class TestStudentFields(AdmitTestCase):
	def test_blueprint_fields_exist_on_student(self):
		meta = frappe.get_meta("Student")
		for fieldname in (
			"oc_company", "oc_register_no", "oc_roll_no", "oc_regulation", "oc_batch", "oc_admission_quota",
			"oc_current_semester", "oc_section", "oc_mentor", "oc_class_advisor", "oc_academic_status",
			"oc_hostel_resident", "oc_transport_user", "oc_abc_id", "oc_first_graduate", "oc_differently_abled",
			"oc_lateral_entry", "oc_onboarding_completion",
		):
			self.assertTrue(meta.has_field(fieldname), fieldname)
		self.assertEqual(
			meta.get_field("oc_academic_status").options.split("\n"),
			["Active", "Detained", "Discontinued", "Completed", "Long Absent", "Break of Study"],
		)

	def test_admit_sets_quota_and_lateral_entry(self):
		self.matrix([(QUOTA, OC, 2)])
		applicant = self.applicant()
		frappe.db.set_value("Student Applicant", applicant, "oc_admission_type", "Lateral")
		student = self.admit_as_officer(applicant)["student"]
		self.assertEqual(frappe.db.get_value("Student", student, ["oc_admission_quota", "oc_lateral_entry"]), (QUOTA, 1))


class TestOnboarding(AdmitTestCase):
	def test_default_template_seeded_per_institution_profile(self):
		company = OTHER_COLLEGE
		frappe.db.delete("Student Onboarding Template", {"company": company})
		frappe.get_doc({"doctype": "Institution Profile", "company": company, "institution_status": "Affiliated"}).insert()
		template = frappe.get_doc("Student Onboarding Template", {"company": company, "is_default": 1})
		self.assertEqual(
			[r.item_code for r in template.items],
			["ID-CARD", "LIBRARY-CARD", "BUS-PASS", "HOSTEL", "MENTOR", "CODE-OF-CONDUCT", "ANTI-RAGGING", "INDUCTION"],
		)
		affidavit = next(r for r in template.items if r.item_code == "ANTI-RAGGING")
		self.assertEqual(affidavit.requires_attachment, 1)
		onboarding.ensure_default_templates()  # idempotent
		self.assertEqual(frappe.db.count("Student Onboarding Template", {"company": company}), 1)

	def test_second_default_for_a_company_is_rejected(self):
		self.ensure_template()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Student Onboarding Template", "template_name": "T18 second default", "company": COLLEGE,
					"is_default": 1, "items": [{"item_code": "X", "title": "X"}],
				}
			).insert()

	def ensure_template(self):
		onboarding.ensure_default_template(COLLEGE)

	def admitted_student(self):
		self.matrix([(QUOTA, OC, 5)])
		return self.admit_as_officer(self.applicant())["student"]

	def test_admission_creates_checklist_from_template(self):
		self.ensure_template()
		student = self.admitted_student()
		checklist = frappe.get_doc("Student Onboarding", {"student": student})
		self.assertEqual(len(checklist.items), 8)
		self.assertEqual({r.status for r in checklist.items}, {"Pending"})
		self.assertEqual(frappe.db.get_value("Student", student, "oc_onboarding_completion"), 0)
		self.assertEqual(onboarding.create_for_student(student), checklist.name)  # idempotent
		self.assertEqual(frappe.db.count("Student Onboarding", {"student": student}), 1)

	def test_no_template_means_no_checklist_and_admission_still_works(self):
		frappe.db.delete("Student Onboarding Template", {"company": COLLEGE})
		student = self.admitted_student()
		self.assertFalse(frappe.db.exists("Student Onboarding", {"student": student}))

	def test_completion_percent_branches(self):
		def rows(*statuses):
			return [frappe._dict(status=s) for s in statuses]

		self.assertEqual(completion_percent(rows("Pending", "Pending")), 0)
		self.assertEqual(completion_percent(rows("Done", "Pending", "Pending", "Pending")), 25)
		self.assertEqual(completion_percent(rows("Done", "Waived", "Pending")), 50)  # waived leaves the denominator
		self.assertEqual(completion_percent(rows("Waived")), 100)
		self.assertEqual(completion_percent([]), 100)

	def test_checklist_rules_and_student_percentage(self):
		self.ensure_template()
		student = self.admitted_student()
		checklist = frappe.get_doc("Student Onboarding", {"student": student})
		by_code = {r.item_code: r for r in checklist.items}
		by_code["ANTI-RAGGING"].status = "Done"
		with self.assertRaises(frappe.ValidationError):  # affidavit needs its upload
			checklist.save()
		checklist.reload()
		by_code = {r.item_code: r for r in checklist.items}
		by_code["ID-CARD"].status = "Waived"
		with self.assertRaises(frappe.ValidationError):  # mandatory items cannot be waived
			checklist.save()
		checklist.reload()
		by_code = {r.item_code: r for r in checklist.items}
		by_code["ANTI-RAGGING"].update({"status": "Done", "attachment": "/private/files/affidavit.pdf"})
		by_code["BUS-PASS"].status = "Waived"
		checklist.save()
		checklist.reload()
		self.assertEqual(checklist.completion, round(100 / 7, 2))
		self.assertEqual(frappe.db.get_value("Student", student, "oc_onboarding_completion"), round(100 / 7, 2))
		row = next(r for r in checklist.items if r.item_code == "ANTI-RAGGING")
		self.assertEqual((row.done_by, bool(row.done_on)), (frappe.session.user, True))


class TestMentors(AdmitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_role_user(HOD, "HOD")
		make_role_user(DEAN, "Dean Academics")
		make_role_user(PLAIN_USER, "Academics User")
		for user in MENTORS:
			make_role_user(user)  # the MENTOR Position Holder grants the Mentor role
		cls.employees = [make_employee(user) for user in MENTORS]
		cls.mentor_group = frappe.get_doc(
			{"doctype": "Student Group", "student_group_name": "T18 Mentor Scope", "group_based_on": "Activity",
			"academic_year": YEAR, "program": PROGRAM}
		).insert().name
		for user in MENTORS:
			frappe.get_doc(
				{"doctype": "Position Holder", "position": "MENTOR", "user": user, "scope_value": cls.mentor_group,
				"from_date": add_days(today(), -30)}
			).insert()

	def setUp(self):
		super().setUp()
		SERIAL[0] += 1
		self.batch = YEAR
		onboarding.ensure_default_template(COLLEGE)
		self.students = [self.make_student(n) for n in range(7)]

	def make_student(self, number):
		SERIAL[0] += 1
		student = frappe.get_doc(
			{
				"doctype": "Student", "first_name": f"T18S{SERIAL[0]}", "student_email_id": f"t18s{SERIAL[0]}@t18.example.com",
				"oc_company": COLLEGE, "oc_batch": YEAR, "oc_register_no": f"T18{SERIAL[0]:05d}", "joining_date": today(), "enabled": 1,
			}
		).insert()
		enrollment = frappe.get_doc(
			{"doctype": "Program Enrollment", "student": student.name, "program": PROGRAM, "academic_year": YEAR, "enrollment_date": today()}
		).insert()
		enrollment.submit()
		return student.name

	def allocate_as(self, user, use_default_mentors=False, **kwargs):
		frappe.set_user(user)
		try:
			mentors = None if use_default_mentors else self.employees
			return api.allocate_mentors(program=PROGRAM, batch=YEAR, mentors=mentors, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def mentees_of(self, employee):
		return set(frappe.get_all("Student", filters={"oc_mentor": employee}, pluck="name"))

	def test_allocation_is_even_round_robin_in_register_order(self):
		result = self.allocate_as(HOD)
		ordered = sorted(self.students, key=lambda s: frappe.db.get_value("Student", s, "oc_register_no"))
		self.assertEqual(result[self.employees[0]], [ordered[0], ordered[3], ordered[6]])
		self.assertEqual(result[self.employees[1]], [ordered[1], ordered[4]])
		self.assertEqual(result[self.employees[2]], [ordered[2], ordered[5]])
		self.assertEqual({e: len(self.mentees_of(e)) for e in self.employees}, {self.employees[0]: 3, self.employees[1]: 2, self.employees[2]: 2})

	def test_allocation_by_student_group(self):
		group = frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": f"T18 Alloc {SERIAL[0]}", "group_based_on": "Activity",
				"academic_year": YEAR, "program": PROGRAM,
				"students": [{"student": s, "active": 1} for s in self.students[:4]],
			}
		).insert()
		frappe.set_user(DEAN)
		try:
			result = api.allocate_mentors(student_group=group.name, mentors=frappe.as_json(self.employees[:2]))
		finally:
			frappe.set_user("Administrator")
		self.assertEqual([len(v) for v in result.values()], [2, 2])
		self.assertFalse(frappe.db.get_value("Student", self.students[5], "oc_mentor"))

	def test_same_input_gives_same_allocation(self):
		first = self.allocate_as(DEAN)
		self.assertEqual(self.allocate_as(HOD), first)

	def test_per_mentor_ceiling(self):
		with self.assertRaises(frappe.ValidationError):
			self.allocate_as(HOD, per_mentor=2)  # 7 over 3 needs 3
		self.assertEqual(len(self.allocate_as(HOD, per_mentor=3)), 3)

	def test_only_hod_or_dean_may_allocate(self):
		with self.assertRaises(frappe.PermissionError):
			self.allocate_as(PLAIN_USER)
		self.assertFalse(frappe.db.exists("Student", {"oc_mentor": ["is", "set"], "name": ["in", self.students]}))

	def test_default_mentors_are_the_position_holders(self):
		result = self.allocate_as(HOD, per_mentor=3, use_default_mentors=True)
		self.assertEqual(set(result), set(self.employees))

	def test_no_position_holders_means_no_mentors_not_userless_employees(self):
		userless = make_userless_employee(COLLEGE)
		frappe.db.delete("Position Holder", {"position": "MENTOR"})
		with self.assertRaises(frappe.ValidationError):
			api.allocate_mentors(program=PROGRAM, batch=YEAR)
		with self.assertRaises(frappe.ValidationError):
			api.allocate_mentors(program=PROGRAM, batch=YEAR, mentors=[userless])
		self.assertFalse(frappe.db.exists("Student", {"oc_mentor": userless}))

	def test_mentor_must_belong_to_the_students_company(self):
		from campus.student_services.mentors import position_employees

		foreign = make_foreign_mentor()
		self.assertIn(foreign, position_employees(OTHER_COLLEGE))
		self.assertNotIn(foreign, position_employees(COLLEGE))
		frappe.set_user(HOD)
		try:
			with self.assertRaises(frappe.ValidationError):
				api.allocate_mentors(program=PROGRAM, batch=YEAR, mentors=[foreign])
		finally:
			frappe.set_user("Administrator")
		result = self.allocate_as(HOD, use_default_mentors=True)
		self.assertNotIn(foreign, result)

	def test_program_cohort_over_the_cap_needs_a_student_group(self):
		with patch("campus.student_services.mentors.MAX_PROGRAM_COHORT", 3):
			with self.assertRaises(frappe.ValidationError):
				self.allocate_as(HOD)
			self.assertFalse(frappe.db.exists("Student", {"oc_mentor": ["is", "set"], "name": ["in", self.students]}))
			group = frappe.get_doc(
				{"doctype": "Student Group", "student_group_name": f"T18 Cap {SERIAL[0]}", "group_based_on": "Activity",
				"academic_year": YEAR, "program": PROGRAM, "students": [{"student": s, "active": 1} for s in self.students]}
			).insert()
			frappe.set_user(HOD)
			try:
				result = api.allocate_mentors(student_group=group.name, mentors=self.employees)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(sum(len(v) for v in result.values()), 7)

	def test_non_holder_is_not_a_mentor(self):
		outsider = make_employee(PLAIN_USER)
		with self.assertRaises(frappe.ValidationError):
			api.allocate_mentors(program=PROGRAM, batch=YEAR, mentors=[outsider])

	def test_ended_holding_drops_the_mentor(self):
		holding = frappe.get_doc("Position Holder", {"position": "MENTOR", "user": MENTORS[2]})
		self.addCleanup(frappe.clear_cache, user=MENTORS[2])  # the rollback restores the role, not its cache
		holding.to_date = add_days(today(), -1)
		holding.save()
		result = self.allocate_as(HOD, use_default_mentors=True)
		self.assertEqual(set(result), set(self.employees[:2]))
		with self.assertRaises(frappe.ValidationError):
			self.allocate_as(HOD)  # naming the lapsed mentor explicitly is refused

	def test_post_only_and_bad_mentors(self):
		self.assertIn("POST", frappe.allowed_http_methods_for_whitelisted_func[api.allocate_mentors])
		with self.assertRaises(frappe.ValidationError):
			api.allocate_mentors(program=PROGRAM, batch=YEAR, mentors=["NO-SUCH-EMP"])

	def test_mentors_see_only_their_mentees(self):
		self.allocate_as(HOD)
		for user, employee in zip(MENTORS, self.employees):
			frappe.set_user(user)
			try:
				seen = set(frappe.get_list("Student", filters={"name": ["in", self.students]}, pluck="name"))
				self.assertEqual(seen, self.mentees_of(employee), user)
				stranger = next(s for s in self.students if s not in seen)
				self.assertFalse(frappe.has_permission("Student", "read", stranger))
				self.assertTrue(frappe.has_permission("Student", "read", next(iter(seen))))
				self.assertFalse(frappe.has_permission("Student", "write", next(iter(seen))))
			finally:
				frappe.set_user("Administrator")

	def test_other_roles_are_not_narrowed(self):
		self.allocate_as(HOD)
		frappe.set_user(PLAIN_USER)
		try:
			self.assertEqual(len(frappe.get_list("Student", filters={"name": ["in", self.students]})), 7)
		finally:
			frappe.set_user("Administrator")

	def test_mentor_assigned_item_ticked_on_checklist(self):
		onboarding.create_for_student(self.students[0])
		self.allocate_as(HOD)
		checklist = frappe.get_doc("Student Onboarding", {"student": self.students[0]})
		self.assertEqual(next(r.status for r in checklist.items if r.item_code == "MENTOR"), "Done")

	def test_class_advisor_resolved_from_position_holder(self):
		group = frappe.get_doc(
			{
				"doctype": "Student Group", "student_group_name": f"T18 Group {SERIAL[0]}", "group_based_on": "Activity",
				"academic_year": YEAR, "program": PROGRAM, "students": [{"student": self.students[0], "active": 1}],
			}
		).insert()
		frappe.get_doc(
			{"doctype": "Position Holder", "position": "CLASS-ADVISOR", "scope_value": group.name, "user": PLAIN_USER, "from_date": add_days(today(), -1)}
		).insert()
		student = frappe.get_doc("Student", self.students[0])
		student.save()
		self.assertEqual(student.oc_class_advisor, PLAIN_USER)


class TestMyOnboarding(AdmitTestCase):
	def test_student_sees_only_own_onboarding(self):
		from campus.student_services.portal import my_onboarding

		onboarding.ensure_default_template(COLLEGE)
		self.matrix([(QUOTA, OC, 5)])
		mine = self.admit_as_officer(self.applicant())["student"]
		other = self.admit_as_officer(self.applicant())["student"]
		make_role_user("t18-student@example.com", "Student")
		self.addCleanup(frappe.clear_cache, user="t18-student@example.com")
		frappe.db.set_value("Student", mine, "user", "t18-student@example.com")
		frappe.set_user("t18-student@example.com")
		try:
			result = my_onboarding()
			self.assertEqual((result["student"], result["completion"], len(result["items"])), (mine, 0, 8))
			self.assertEqual(set(result["items"][0]), {"title", "mandatory", "status"})
			with self.assertRaises(frappe.PermissionError):
				my_onboarding(other)
		finally:
			frappe.set_user("Administrator")


class TestCleanup(AdmitTestCase):
	def test_old_names_are_gone(self):
		from campus.patches.remove_wip_onboarding_checklists import OLD_DOCTYPES

		for name in OLD_DOCTYPES:
			self.assertFalse(frappe.db.exists("DocType", name), name)
			self.assertFalse(frappe.db.table_exists(name), name)


class TestIdCardEscaping(AdmitTestCase):
	def test_name_and_photo_are_escaped_on_the_card(self):
		onboarding.ensure_default_template(COLLEGE)
		self.matrix([(QUOTA, OC, 2)])
		student = self.admit_as_officer(self.applicant())["student"]
		frappe.db.set_value("Student", student, {"student_name": "<script>alert(1)</script>", "image": '/x.png" onerror="y'})
		html = frappe.get_print("Student", student, "Student ID Card")
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertNotIn('onerror="y', html)


class TestMenteeGuard(AdmitTestCase):
	def test_blank_user_has_no_mentees(self):
		from campus.examinations.access import mentees_of

		make_userless_employee(COLLEGE)
		self.assertEqual(mentees_of(""), set())
		self.assertEqual(mentees_of(None), set())


class TestIdCard(AdmitTestCase):
	def test_id_card_prints_photo_and_verifiable_qr(self):
		onboarding.ensure_default_template(COLLEGE)
		self.matrix([(QUOTA, OC, 2)])
		student = self.admit_as_officer(self.applicant())["student"]
		frappe.db.set_value("Student", student, {"image": "/files/t18-photo.png", "blood_group": "B+"})
		before = frappe.get_print("Student", student, "Student ID Card")
		self.assertIn("/files/t18-photo.png", before)
		self.assertNotIn("oc-qr-block", before)  # nothing issued yet
		frappe.set_user(self.officer_user())
		try:
			issued = api.issue_id_card(student)
		finally:
			frappe.set_user("Administrator")
		html = frappe.get_print("Student", student, "Student ID Card")
		register_no = frappe.db.get_value("Student", student, "oc_register_no")
		for text in (issued["code"], issued["url"], register_no, PROGRAM, "B+", "data:image/png;base64"):
			self.assertIn(text, html)
		onboarding_row = frappe.get_doc("Student Onboarding", {"student": student}).items[0]
		self.assertEqual((onboarding_row.item_code, onboarding_row.status), ("ID-CARD", "Done"))
		found = verify(issued["code"])
		self.assertEqual((found.status, found.company), ("Valid", COLLEGE))

	def officer_user(self):
		from campus.tests.test_admission_flow import OFFICER

		frappe.get_doc("User", OFFICER).add_roles("Academics User")
		return OFFICER
