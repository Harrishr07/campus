"""M17-02 tests: position resolution by date, overlap rule, role grant/revoke and seed data."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.api import resolve_position
from campus.campus_platform.positions import (
	SEED_POSITIONS,
	date_ranges_overlap,
	ensure_seed_positions,
	sync_all_roles,
)
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE = "Position Test College"
ALICE = "pos-alice@example.com"
BOB = "pos-bob@example.com"
CAROL = "pos-carol@example.com"
DEPT = "Position Test CSE"


def make_department(name, company):
	existing = frappe.db.get_value("Department", {"department_name": name, "company": company})
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Department", "department_name": name, "company": company}).insert().name


def holding(position, user, from_date, to_date=None, scope=None, **extra):
	return frappe.get_doc(
		{
			"doctype": "Position Holder",
			"position": position,
			"scope_value": scope,
			"user": user,
			"from_date": from_date,
			"to_date": to_date,
			**extra,
		}
	)


def roles_of(user):
	return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))


class TestDateRangeOverlap(CampusTestCase):
	def test_disjoint_ranges(self):
		self.assertFalse(date_ranges_overlap("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"))
		self.assertFalse(date_ranges_overlap("2026-02-01", "2026-02-28", "2026-01-01", "2026-01-31"))

	def test_shared_boundary_day_overlaps(self):
		self.assertTrue(date_ranges_overlap("2026-01-01", "2026-02-01", "2026-02-01", "2026-02-28"))

	def test_open_ended_ranges(self):
		self.assertTrue(date_ranges_overlap("2026-01-01", None, "2030-01-01", "2030-02-01"))
		self.assertTrue(date_ranges_overlap("2030-01-01", "2030-02-01", "2026-01-01", None))
		self.assertTrue(date_ranges_overlap("2026-01-01", None, "2025-01-01", None))
		self.assertFalse(date_ranges_overlap("2026-01-01", None, "2024-01-01", "2025-12-31"))


class TestPositions(CampusTestCase):
	@classmethod
	def load_demo_data(cls):
		ensure_seed_positions()
		make_company(COLLEGE, "PTC")
		for user in (ALICE, BOB, CAROL):
			make_user(user, [COLLEGE])
		cls.dept = make_department(DEPT, COLLEGE)

	def setUp(self):
		commit = patch.object(frappe.db, "commit")  # sync_all_roles commits per user; keep tests rolled back
		commit.start()
		self.addCleanup(commit.stop)
		frappe.db.delete("Position Holder")
		for user in (ALICE, BOB, CAROL):
			frappe.get_doc("User", user).remove_roles("HOD", "Mentor", "Dean Academics")

	def test_seed_positions_are_idempotent_and_complete(self):
		ensure_seed_positions()
		ensure_seed_positions()
		self.assertEqual(frappe.db.count("Position", {"name": ["in", [row[0] for row in SEED_POSITIONS]]}), 9)
		for code, _title, scope_type, role, single in SEED_POSITIONS:
			position = frappe.get_doc("Position", code)
			self.assertEqual((position.scope_type, position.role, position.single_holder), (scope_type, role, single))
			self.assertTrue(frappe.db.exists("Role", role))
		self.assertEqual(frappe.db.get_value("Position", "MENTOR", "single_holder"), 0)

	def test_resolves_current_and_past_holder(self):
		holding("HOD", ALICE, "2020-01-01", "2026-06-30", scope=self.dept).insert()
		holding("HOD", BOB, "2026-07-01", scope=self.dept).insert()
		self.assertEqual(resolve_position("HOD", self.dept, "2026-10-04"), [BOB])
		self.assertEqual(resolve_position("HOD", self.dept, "2025-03-01"), [ALICE])
		self.assertEqual(resolve_position("HOD", self.dept, "2026-06-30"), [ALICE])
		self.assertEqual(resolve_position("HOD", self.dept, "2019-12-31"), [])
		self.assertEqual(resolve_position("HOD", self.dept), [BOB])

	def test_resolve_filters_by_scope(self):
		other = make_department("Position Test ECE", COLLEGE)
		holding("HOD", ALICE, "2020-01-01", scope=self.dept).insert()
		holding("HOD", BOB, "2020-01-01", scope=other).insert()
		self.assertEqual(resolve_position("HOD", other), [BOB])
		self.assertCountEqual(resolve_position("HOD"), [ALICE, BOB])

	def test_multi_holder_position_lists_all_ordered_by_start(self):
		group = self.make_student_group()
		holding("MENTOR", BOB, "2026-02-01", scope=group).insert()
		holding("MENTOR", ALICE, "2026-01-01", scope=group).insert()
		self.assertEqual(resolve_position("MENTOR", group, "2026-10-04"), [ALICE, BOB])

	def test_single_holder_overlap_is_rejected(self):
		holding("HOD", ALICE, "2026-01-01", "2026-06-30", scope=self.dept).insert()
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", BOB, "2026-06-30", scope=self.dept).insert()
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", BOB, "2025-01-01", "2026-01-01", scope=self.dept).insert()

	def test_single_holder_non_overlapping_and_other_scope_allowed(self):
		holding("HOD", ALICE, "2026-01-01", "2026-06-30", scope=self.dept).insert()
		holding("HOD", BOB, "2026-07-01", scope=self.dept).insert()
		other = make_department("Position Test ME", COLLEGE)
		holding("HOD", CAROL, "2026-01-01", scope=other).insert()

	def test_editing_a_holding_does_not_clash_with_itself(self):
		doc = holding("HOD", ALICE, "2026-01-01", scope=self.dept).insert()
		doc.to_date = "2026-12-31"
		doc.save()

	def test_to_date_before_from_date_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", ALICE, "2026-02-01", "2026-01-01", scope=self.dept).insert()

	def test_scope_must_exist_for_doctype_scopes(self):
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", ALICE, "2026-01-01", scope="No Such Department").insert()
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", ALICE, "2026-01-01").insert()

	def test_free_text_scope_for_hostel(self):
		doc = holding("WARDEN", ALICE, "2026-01-01", scope="Block B").insert()
		self.assertFalse(doc.scope_doctype)
		self.assertEqual(resolve_position("WARDEN", "Block B"), [ALICE])

	def test_user_derived_from_employee(self):
		employee = self.make_employee(BOB)
		doc = holding("HOD", None, "2026-01-01", scope=self.dept, employee=employee).insert()
		self.assertEqual(doc.user, BOB)

	def test_employee_without_user_rejected(self):
		employee = self.make_employee(None)
		with self.assertRaises(frappe.ValidationError):
			holding("HOD", None, "2026-01-01", scope=self.dept, employee=employee).insert()

	def test_role_granted_when_holding_active(self):
		self.assertNotIn("HOD", roles_of(ALICE))
		holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		self.assertIn("HOD", roles_of(ALICE))

	def test_role_not_granted_for_future_or_past_holding(self):
		holding("HOD", ALICE, add_days(today(), 3), scope=self.dept).insert()
		holding("HOD", BOB, add_days(today(), -9), add_days(today(), -2), scope=self.dept).insert()
		self.assertNotIn("HOD", roles_of(ALICE))
		self.assertNotIn("HOD", roles_of(BOB))

	def test_daily_job_grants_role_when_holding_starts_today(self):
		doc = holding("HOD", ALICE, add_days(today(), 1), scope=self.dept).insert()
		frappe.db.set_value("Position Holder", doc.name, "from_date", today())  # the day arrives
		sync_all_roles()
		self.assertIn("HOD", roles_of(ALICE))

	def test_daily_job_revokes_role_the_day_after_holding_ends(self):
		doc = holding("HOD", ALICE, add_days(today(), -5), today(), scope=self.dept).insert()
		sync_all_roles()
		self.assertIn("HOD", roles_of(ALICE))  # ends today: still holds today
		frappe.db.set_value("Position Holder", doc.name, "to_date", add_days(today(), -1))  # next day
		sync_all_roles()
		self.assertNotIn("HOD", roles_of(ALICE))

	def test_role_kept_while_another_active_holding_grants_it(self):
		dept2 = make_department("Position Test EEE", COLLEGE)
		first = holding("HOD", ALICE, add_days(today(), -9), scope=self.dept).insert()
		holding("HOD", ALICE, add_days(today(), -9), scope=dept2).insert()
		frappe.db.set_value("Position Holder", first.name, "to_date", add_days(today(), -1))
		sync_all_roles()
		self.assertIn("HOD", roles_of(ALICE))
		# the mark moved: when the second holding ends too, the role goes
		frappe.db.set_value("Position Holder", {"user": ALICE}, "to_date", add_days(today(), -1))
		sync_all_roles()
		self.assertNotIn("HOD", roles_of(ALICE))

	def test_role_kept_when_another_position_grants_the_same_role(self):
		frappe.get_doc("Position", "MENTOR").db_set("role", "HOD")
		self.addCleanup(lambda: frappe.get_doc("Position", "MENTOR").db_set("role", "Mentor"))
		group = self.make_student_group()
		hod = holding("HOD", ALICE, add_days(today(), -9), scope=self.dept).insert()
		holding("MENTOR", ALICE, add_days(today(), -9), scope=group).insert()
		frappe.db.set_value("Position Holder", hod.name, "to_date", add_days(today(), -1))
		sync_all_roles()
		self.assertIn("HOD", roles_of(ALICE))

	def test_manually_assigned_role_is_never_removed(self):
		frappe.get_doc("User", ALICE).add_roles("HOD")
		doc = holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		frappe.db.set_value("Position Holder", doc.name, "to_date", add_days(today(), -1))
		sync_all_roles()
		self.assertIn("HOD", roles_of(ALICE))

	def test_deleting_a_holding_removes_its_role(self):
		doc = holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		self.assertIn("HOD", roles_of(ALICE))
		doc.delete()
		self.assertNotIn("HOD", roles_of(ALICE))

	def test_changing_holder_user_moves_the_role(self):
		doc = holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		doc.user = BOB
		doc.save()
		self.assertNotIn("HOD", roles_of(ALICE))
		self.assertIn("HOD", roles_of(BOB))

	def test_position_cannot_be_changed_after_creation(self):
		doc = holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		doc.position = "COE"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertIn("HOD", roles_of(ALICE))

	def test_unknown_position_gives_validation_error(self):
		with self.assertRaises(frappe.ValidationError):
			holding("NO-SUCH", ALICE, "2026-01-01").insert()

	def test_one_failing_user_does_not_stop_the_sync(self):
		from campus.campus_platform import positions

		doc = holding("HOD", ALICE, add_days(today(), -5), scope=self.dept).insert()
		frappe.db.set_value("Position Holder", doc.name, "to_date", add_days(today(), -1))
		holding("HOD", BOB, add_days(today(), -5), scope=make_department("Position Test CE", COLLEGE)).insert()
		real = positions.sync_user_roles

		def flaky(user, *args, **kwargs):
			if user == BOB:
				raise RuntimeError("boom")
			return real(user, *args, **kwargs)

		with patch.object(positions, "sync_user_roles", flaky), patch.object(frappe, "log_error") as log:
			sync_all_roles()
		self.assertTrue(log.called)
		self.assertNotIn("HOD", roles_of(ALICE))

	def make_student_group(self):
		name = "Position Test Group"
		if not frappe.db.exists("Academic Year", "PT-2026"):
			frappe.get_doc(
				{
					"doctype": "Academic Year",
					"academic_year_name": "PT-2026",
					"year_start_date": "2026-06-01",
					"year_end_date": "2027-05-31",
				}
			).insert()
		if not frappe.db.exists("Student Group", name):
			frappe.get_doc(
				{
					"doctype": "Student Group",
					"student_group_name": name,
					"group_based_on": "Activity",
					"academic_year": "PT-2026",
					"oc_company": COLLEGE,
				}
			).insert()
		return frappe.db.get_value("Student Group", {"student_group_name": name})

	def make_employee(self, user):
		if not frappe.db.exists("Gender", "Female"):
			frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert()
		first_name = f"Pos Emp {user or 'nouser'}"
		existing = frappe.db.get_value("Employee", {"first_name": first_name})
		if existing:
			return existing
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": first_name,
				"gender": "Female",
				"date_of_birth": "1985-01-01",
				"date_of_joining": "2020-01-01",
				"company": COLLEGE,
				"user_id": user,
				"status": "Active",
			}
		).insert().name
