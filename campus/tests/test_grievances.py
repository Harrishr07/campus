"""P1-T21 tests (M05-06): grievance categories on HRMS Grievance Type, SLA escalation HOD -> COE -> Principal through the
approval engine, resolution, confidentiality through the permission hooks, ownership-checked portal helpers, the SLA report."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, time_diff_in_hours, today

from campus.campus_platform import approval_rules as rules
from campus.campus_platform.approval_escalation import escalate_overdue as generic_escalate_overdue
from campus.student_services import grievances, portal
from campus.student_services.report.grievance_sla import grievance_sla
from campus.student_services.setup import GRIEVANCE_POLICY
from campus.tests.approval_fixtures import level, make_department
from campus.tests.factories import make_user
from campus.tests.broadcast_fixtures import make_guardian
from campus.tests.finance_factories import make_enrolled_students, make_finance_company, make_year_and_program
from campus.tests.test_results import make_login
from campus.tests.utils import CampusTestCase

COLLEGE = "Grievance Test College"
YEAR, PROGRAM = "Grievance Test 2026", "Grievance Test BE"
POLICY, ICC_POLICY = "GRV Test Escalation", "GRV Test Committee"
EVALUATION, ICC, STAFF_ONLY = "GRV Test Evaluation", "GRV Test ICC", "GRV Test Staff Only"
HOD, COE, PRINCIPAL, COMMITTEE = "grv-hod@example.com", "grv-coe@example.com", "grv-principal@example.com", "grv-committee@example.com"
STUDENT_A, STUDENT_B = "grv-student-a@example.com", "grv-student-b@example.com"
HOD_B, GUARDIAN = "grv-hod-b@example.com", "grv-guardian@example.com"


def make_category(name, policy, **values):
	if frappe.db.exists("Grievance Type", name):
		frappe.delete_doc("Grievance Type", name, force=True)
	return frappe.get_doc(
		{"doctype": "Grievance Type", "__newname": name, "oc_applies_to_students": 1, "oc_escalation_policy": policy, **values}
	).insert()


def hold(position, scope, user):
	if not frappe.db.exists("Position Holder", {"position": position, "scope_value": scope}):
		frappe.get_doc(
			{"doctype": "Position Holder", "position": position, "scope_value": scope, "user": user, "from_date": add_days(today(), -30)}
		).insert()


class GrievanceFixture(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_finance_company(COLLEGE, "GRVC")
		make_year_and_program(COLLEGE, PROGRAM, YEAR)
		cls.department = make_department("Grievance Test CSE", COLLEGE)
		frappe.db.set_value("Program", PROGRAM, "department", cls.department)
		_group, students = make_enrolled_students(COLLEGE, PROGRAM, YEAR, 2, "GrvStu")
		cls.a, cls.b = students
		for user in (HOD, COE, PRINCIPAL):
			make_user(user, [COLLEGE])
		make_user(COMMITTEE, [COLLEGE])
		frappe.get_doc("User", COMMITTEE).add_roles("Grievance Committee")
		cls.department_b = make_department("Grievance Test ECE", COLLEGE)
		make_user(HOD_B, [COLLEGE])
		hold("HOD", cls.department_b, HOD_B)
		make_login(GUARDIAN, "Guardian")
		make_guardian("Grvguardian", [cls.a], user=GUARDIAN)
		hold("HOD", cls.department, HOD)
		hold("COE", COLLEGE, COE)
		hold("PRINCIPAL", COLLEGE, PRINCIPAL)
		for key, student in ((STUDENT_A, cls.a), (STUDENT_B, cls.b)):
			make_login(key, "Student")
			frappe.db.set_value("Student", student, "user", key)

	def setUp(self):
		frappe.db.savepoint("grievance_test")
		self.addCleanup(frappe.db.rollback, save_point="grievance_test")
		self.addCleanup(frappe.set_user, "Administrator")
		commit = patch.object(frappe.db, "commit")  # the job commits per request; keep tests rolled back
		commit.start()
		self.addCleanup(commit.stop)
		self.make_policy(POLICY, [
			level("Position", "HOD", title="HOD", scope_field="department", sla_hours=24),
			level("Position", "COE", title="COE", scope_field="company", sla_hours=48),
			level("Position", "PRINCIPAL", title="Principal", scope_field="company", sla_hours=72),
		])  # fmt: skip
		self.make_policy(ICC_POLICY, [level("Role", "Grievance Committee", title="Committee", sla_hours=24)])
		make_category(EVALUATION, POLICY)
		make_category(ICC, ICC_POLICY, oc_confidential=1)

	def make_policy(self, name, levels):
		frappe.db.delete("Approval Level", {"parent": name})
		frappe.db.delete("Approval Policy", {"name": name})
		frappe.get_doc(
			{"doctype": "Approval Policy", "policy_name": name, "document_type": "Student Grievance", "levels": levels}
		).insert()

	def raise_for(self, student=None, category=EVALUATION):
		return grievances.open_grievance(student or self.a, category, "Marks were not added up correctly.")

	def request_of(self, grievance):
		return frappe.get_doc("Approval Request", frappe.db.get_value("Approval Request", {"reference_name": grievance.name}))

	def make_overdue(self, request):
		frappe.db.set_value("Approval Request", request.name, "due_at", add_to_date(now_datetime(), hours=-1))
		return frappe.get_doc("Approval Request", request.name)


class TestEscalation(GrievanceFixture):
	def test_raising_starts_the_first_level_with_the_hod_of_the_students_department(self):
		grievance = self.raise_for()
		self.assertEqual((grievance.status, grievance.company, grievance.department), ("Open", COLLEGE, self.department))
		request = self.request_of(grievance)
		self.assertEqual((request.status, request.current_level, request.policy), ("Pending", 1, POLICY))
		self.assertEqual([r.user for r in request.approvers], [HOD])
		self.assertAlmostEqual(time_diff_in_hours(request.due_at, request.level_started_at), 24, places=1)

	def test_an_evaluation_grievance_escalates_from_hod_to_coe_to_principal(self):
		request = self.request_of(self.raise_for())
		for level_no, approver, hours in ((2, COE, 48), (3, PRINCIPAL, 72)):
			self.assertTrue(grievances.escalate(self.make_overdue(request).name))
			request = frappe.get_doc("Approval Request", request.name)
			self.assertEqual(request.current_level, level_no)
			self.assertEqual([r.user for r in request.approvers if r.level == level_no], [approver])
			self.assertAlmostEqual(time_diff_in_hours(request.due_at, now_datetime()), hours, places=1)
		trail = [(a.action, a.level) for a in request.actions]
		self.assertEqual(trail.count((rules.ESCALATE, 1)), 1)
		self.assertEqual(trail.count((rules.ESCALATE, 2)), 1)

	def test_escalation_is_idempotent_and_waits_for_the_deadline(self):
		request = self.request_of(self.raise_for())
		self.assertFalse(grievances.escalate(request.name))  # not yet due
		self.make_overdue(request)
		self.assertTrue(grievances.escalate(request.name))
		self.assertFalse(grievances.escalate(request.name))  # the new level's deadline is in the future
		self.assertEqual(frappe.db.get_value("Approval Request", request.name, "current_level"), 2)

	def test_the_last_level_has_nowhere_to_escalate(self):
		request = self.request_of(self.raise_for())
		for _n in range(2):
			grievances.escalate(self.make_overdue(request).name)
		self.assertFalse(grievances.escalate(self.make_overdue(request).name))
		self.assertEqual(frappe.db.get_value("Approval Request", request.name, "current_level"), 3)

	def test_the_hourly_job_escalates_every_overdue_grievance_once(self):
		first, second = self.raise_for(self.a), self.raise_for(self.b)
		self.make_overdue(self.request_of(first))
		grievances.escalate_overdue()
		grievances.escalate_overdue()
		self.assertEqual(self.request_of(first).current_level, 2)
		self.assertEqual(self.request_of(second).current_level, 1)

	def test_a_resolved_grievance_is_not_escalated(self):
		grievance = self.raise_for()
		request = self.make_overdue(self.request_of(grievance))
		frappe.set_user(HOD)
		grievances.resolve(grievance.name, "Marks corrected.")
		frappe.set_user("Administrator")
		self.assertFalse(grievances.escalate(request.name))

	def test_a_level_that_cannot_resolve_approvers_fails_without_moving_and_does_not_stop_the_job(self):
		frappe.db.set_value("Position Holder", {"position": "COE", "scope_value": COLLEGE}, "to_date", add_days(today(), -1))
		request = self.request_of(self.raise_for())
		self.make_overdue(request)
		with patch("campus.student_services.grievances.frappe.log_error") as log:
			grievances.escalate_overdue()
		self.assertEqual(self.request_of(frappe.get_doc("Student Grievance", request.reference_name)).current_level, 1)
		log.assert_called_once()
		self.assertEqual(frappe.db.get_value("Student Grievance", request.reference_name, "docstatus"), 0)


class TestResolution(GrievanceFixture):
	def test_the_current_approver_resolves_and_the_request_closes(self):
		grievance = self.raise_for()
		frappe.set_user(HOD)
		self.assertEqual(grievances.resolve(grievance.name, "Re-evaluated; marks revised."), "Resolved")
		frappe.set_user("Administrator")
		grievance.reload()
		self.assertEqual((grievance.docstatus, grievance.status, grievance.resolved_by), (1, "Resolved", HOD))
		self.assertEqual(self.request_of(grievance).status, "Approved")

	def test_an_escalated_away_hod_can_no_longer_resolve(self):
		grievance = self.raise_for()
		grievances.escalate(self.make_overdue(self.request_of(grievance)).name)
		frappe.set_user(HOD)
		with self.assertRaises(frappe.PermissionError):
			grievances.resolve(grievance.name, "Too late.")
		frappe.set_user(COE)
		grievances.resolve(grievance.name, "Resolved at COE.")

	def test_a_resolution_text_is_required(self):
		grievance = self.raise_for()
		frappe.set_user(HOD)
		with self.assertRaisesRegex(frappe.ValidationError, "resolution"):
			grievances.resolve(grievance.name, " ")

	def test_the_student_cannot_resolve_their_own_grievance(self):
		grievance = self.raise_for()
		frappe.set_user(STUDENT_A)
		with self.assertRaises(frappe.PermissionError):
			grievances.resolve(grievance.name, "Fine.")

	def test_a_category_not_open_to_students_is_refused(self):
		make_category(STAFF_ONLY, POLICY, oc_applies_to_students=0)
		with self.assertRaisesRegex(frappe.ValidationError, "not a student grievance category"):
			self.raise_for(category=STAFF_ONLY)

	def test_a_category_without_a_policy_is_refused(self):
		make_category(STAFF_ONLY, None)
		with self.assertRaisesRegex(frappe.ValidationError, "no escalation policy"):
			self.raise_for(category=STAFF_ONLY)


class TestConfidentiality(GrievanceFixture):
	def setUp(self):
		super().setUp()
		self.open = self.raise_for(self.a, EVALUATION)
		self.icc = self.raise_for(self.a, ICC)
		self.other = self.raise_for(self.b, EVALUATION)

	def visible(self, user):
		frappe.set_user(user)
		return set(frappe.get_list("Student Grievance", pluck="name"))

	def test_the_confidential_flag_comes_from_the_category(self):
		self.assertEqual((self.open.is_confidential, self.icc.is_confidential), (0, 1))

	def test_the_hod_sees_ordinary_grievances_but_never_a_confidential_one(self):
		seen = self.visible(HOD)
		self.assertIn(self.open.name, seen)
		self.assertNotIn(self.icc.name, seen)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Student Grievance", self.icc.name).check_permission("read")

	def test_the_committee_and_system_manager_see_confidential_grievances(self):
		for user in (COMMITTEE, "Administrator"):
			self.assertTrue({self.open.name, self.icc.name} <= self.visible(user), user)
		frappe.set_user(COMMITTEE)
		frappe.get_doc("Student Grievance", self.icc.name).check_permission("read")

	def test_the_committee_resolves_a_confidential_grievance_through_its_own_policy(self):
		frappe.set_user(COMMITTEE)
		grievances.resolve(self.icc.name, "ICC inquiry closed.")
		self.assertEqual(frappe.db.get_value("Student Grievance", self.icc.name, "status"), "Resolved")

	def test_a_student_sees_only_their_own_grievances_confidential_ones_included(self):
		self.assertEqual(self.visible(STUDENT_A), {self.open.name, self.icc.name})
		self.assertEqual(self.visible(STUDENT_B), {self.other.name})
		frappe.set_user(STUDENT_B)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Student Grievance", self.open.name).check_permission("read")


class TestPortal(GrievanceFixture):
	def test_a_student_raises_and_lists_their_grievance(self):
		frappe.set_user(STUDENT_A)
		row = portal.raise_grievance(EVALUATION, "  Revaluation result is missing.  ")
		self.assertEqual((row["category"], row["status"], row["description"]), (EVALUATION, "Open", "Revaluation result is missing."))
		mine = portal.my_grievances()
		self.assertEqual([g["name"] for g in mine["grievances"]], [row["name"]])
		frappe.set_user(STUDENT_B)
		self.assertEqual(portal.my_grievances()["grievances"], [])

	def test_the_student_is_resolved_from_the_session_not_the_request(self):
		frappe.set_user(STUDENT_A)
		with self.assertRaises(frappe.PermissionError):
			portal.raise_grievance(EVALUATION, "For my friend.", student=self.b)
		with self.assertRaises(frappe.PermissionError):
			portal.my_grievances(student=self.b)

	def test_a_guest_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			portal.raise_grievance(EVALUATION, "Hello")

	def test_the_student_sees_the_resolution(self):
		frappe.set_user(STUDENT_A)
		name = portal.raise_grievance(EVALUATION, "Marks.")["name"]
		frappe.set_user(HOD)
		grievances.resolve(name, "Marks revised.")
		frappe.set_user(STUDENT_A)
		row = portal.my_grievances()["grievances"][0]
		self.assertEqual((row["status"], row["resolution"]), ("Resolved", "Marks revised."))

	def test_only_student_categories_are_offered(self):
		make_category(STAFF_ONLY, POLICY, oc_applies_to_students=0)
		frappe.set_user(STUDENT_A)
		names = [c["name"] for c in portal.grievance_categories()]
		self.assertIn(EVALUATION, names)
		self.assertNotIn(STAFF_ONLY, names)


class TestSlaReport(GrievanceFixture):
	def run_report(self, user="Administrator", **filters):
		frappe.set_user(user)
		return grievance_sla.execute({"company": COLLEGE, **filters})[1]

	def test_rows_show_level_deadline_escalations_and_sla_state(self):
		late, fresh, closed = self.raise_for(self.a), self.raise_for(self.b), self.raise_for(self.a)
		grievances.escalate(self.make_overdue(self.request_of(late)).name)
		self.make_overdue(self.request_of(late))
		frappe.set_user(HOD)
		grievances.resolve(closed.name, "Done.")
		rows = {r["name"]: r for r in self.run_report()}
		self.assertEqual((rows[late.name]["current_level"], rows[late.name]["escalations"], rows[late.name]["sla"]), (2, 1, "Overdue"))
		self.assertEqual((rows[fresh.name]["current_level"], rows[fresh.name]["sla"]), (1, "Within SLA"))
		self.assertEqual((rows[closed.name]["sla"], rows[closed.name]["due_at"]), ("Closed", None))

	def test_the_report_hides_confidential_rows_from_the_hod_and_filters_by_company(self):
		icc = self.raise_for(self.a, ICC)
		ordinary = self.raise_for(self.a)
		self.assertNotIn(icc.name, {r["name"] for r in self.run_report(HOD)})
		self.assertIn(ordinary.name, {r["name"] for r in self.run_report(HOD)})
		self.assertIn(icc.name, {r["name"] for r in self.run_report(COMMITTEE)})
		self.assertEqual(self.run_report(company="Some Other Company"), [])


class TestSetup(CampusTestCase):
	def test_grievance_type_carries_the_campus_fields_and_no_second_category_doctype_exists(self):
		meta = frappe.get_meta("Grievance Type")
		for fieldname in ("oc_applies_to_students", "oc_confidential", "oc_escalation_policy"):
			self.assertTrue(meta.has_field(fieldname), fieldname)
		self.assertFalse(frappe.db.exists("DocType", "Grievance Category"))

	def test_the_default_policy_is_hod_coe_principal_with_sla_hours(self):
		policy = frappe.get_doc("Approval Policy", GRIEVANCE_POLICY)
		self.assertEqual([(lv.approver, lv.sla_hours) for lv in policy.levels], [("HOD", 48), ("COE", 48), ("PRINCIPAL", 72)])
		self.assertEqual(frappe.db.get_value("Grievance Type", "Evaluation", "oc_escalation_policy"), GRIEVANCE_POLICY)


class TestFixRound1(GrievanceFixture):
	def seat_ended(self, position, scope):
		frappe.db.set_value("Position Holder", {"position": position, "scope_value": scope}, "to_date", add_days(today(), -1))

	def test_the_generic_escalation_job_leaves_grievances_to_the_grievance_job(self):
		grievance = self.raise_for()
		request = self.request_of(grievance)
		self.make_overdue(request)
		generic_escalate_overdue()
		grievances.escalate_overdue()
		request = self.request_of(grievance)
		self.assertEqual(request.current_level, 2)
		self.assertEqual([a.action for a in request.actions].count(rules.ESCALATE), 1)
		self.assertFalse([s for s in notified_grievance(COE) if s.startswith("Overdue approval")])
		self.assertEqual(request.escalated, 0)

	def test_a_category_policy_must_be_a_student_grievance_policy(self):
		other = frappe.get_doc({"doctype": "Approval Policy", "policy_name": "GRV Test Other", "document_type": "Fee Concession",
			"levels": [level("User", COMMITTEE)]}).insert()  # fmt: skip
		with self.assertRaisesRegex(frappe.ValidationError, "Student Grievance policy"):
			make_category(STAFF_ONLY, other.name)

	def test_a_confidential_category_needs_a_committee_only_policy(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Grievance Committee"):
			make_category(STAFF_ONLY, POLICY, oc_confidential=1)
		make_category(STAFF_ONLY, ICC_POLICY, oc_confidential=1)

	def test_a_vacant_hod_seat_does_not_refuse_the_complaint(self):
		self.seat_ended("HOD", self.department)
		grievance = self.raise_for()
		request = self.request_of(grievance)
		self.assertEqual((grievance.docstatus, request.current_level), (0, 2))
		self.assertEqual([r.user for r in request.approvers], [COE])

	def test_a_student_without_a_department_still_gets_a_routed_grievance(self):
		frappe.db.set_value("Program", PROGRAM, "department", None)
		request = self.request_of(self.raise_for())
		self.assertEqual(request.current_level, 2)

	def test_with_no_resolvable_level_the_committee_handles_it_and_the_student_sees_no_internals(self):
		for position, scope in (("HOD", self.department), ("COE", COLLEGE), ("PRINCIPAL", COLLEGE)):
			self.seat_ended(position, scope)
		frappe.set_user(STUDENT_A)
		row = portal.raise_grievance(EVALUATION, "Nobody is listening.")
		frappe.set_user("Administrator")
		self.assertEqual(row["status"], "Open")
		self.assertFalse(frappe.db.exists("Approval Request", {"reference_name": row["name"]}))
		self.assertTrue(notified_grievance(COMMITTEE))
		frappe.set_user(HOD)
		with self.assertRaises(frappe.PermissionError):
			grievances.resolve(row["name"], "Not mine.")
		frappe.set_user(COMMITTEE)
		self.assertEqual(grievances.resolve(row["name"], "Heard by the committee."), "Resolved")

	def test_a_guardian_reads_ordinary_grievances_of_their_ward_but_never_a_confidential_one(self):
		ordinary, icc = self.raise_for(self.a, EVALUATION), self.raise_for(self.a, ICC)
		frappe.set_user(GUARDIAN)
		self.assertEqual(set(frappe.get_list("Student Grievance", pluck="name")), {ordinary.name})
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Student Grievance", icc.name).check_permission("read")
		self.assertEqual([g["name"] for g in portal.my_grievances()["grievances"]], [ordinary.name])
		frappe.set_user(STUDENT_A)
		self.assertEqual({g["name"] for g in portal.my_grievances()["grievances"]}, {ordinary.name, icc.name})

	def test_a_hod_sees_only_their_department_or_grievances_they_handled(self):
		grievance = self.raise_for(self.a)  # department A
		for user, expected in ((HOD, True), (HOD_B, False), (COE, False), (PRINCIPAL, True)):
			frappe.set_user(user)
			self.assertEqual(grievance.name in frappe.get_list("Student Grievance", pluck="name"), expected, user)
			self.assertEqual(frappe.has_permission("Student Grievance", "read", grievance.name), expected, user)
			frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError):
			frappe.set_user(HOD_B)
			grievances.resolve(grievance.name, "Not my department.")

	def test_the_coe_sees_a_grievance_once_it_is_escalated_to_them_and_keeps_seeing_it(self):
		grievance = self.raise_for(self.a)
		grievances.escalate(self.make_overdue(self.request_of(grievance)).name)
		frappe.set_user(COE)
		self.assertIn(grievance.name, frappe.get_list("Student Grievance", pluck="name"))
		frappe.set_user(HOD)  # was an approver, still department HOD
		self.assertIn(grievance.name, frappe.get_list("Student Grievance", pluck="name"))

	def test_a_past_handler_outside_the_department_keeps_sight_of_what_they_handled(self):
		self.seat_ended("HOD", self.department)
		grievance = self.raise_for(self.a)  # routed to the COE (level 2)
		frappe.set_user(COE)
		self.assertIn(grievance.name, frappe.get_list("Student Grievance", pluck="name"))

	def test_resolve_is_post_only_and_a_description_has_a_length_cap(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[grievances.resolve], ["POST"])
		with self.assertRaisesRegex(frappe.ValidationError, "too long"):
			grievances.open_grievance(self.a, EVALUATION, "x" * 5001)


def notified_grievance(user):
	return frappe.get_all("Notification Log", filters={"for_user": user, "document_type": "Student Grievance"}, pluck="subject")
