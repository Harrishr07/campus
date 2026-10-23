"""M10-01 integration tests: hostel masters, capacity from beds, gender rule, served colleges, fee rates."""

import frappe
from frappe.utils import add_days, today

from campus.campus_finance.fee_heads import seed_fee_categories
from campus.hostel.api import add_beds, fee_rate, served_colleges, validate_allotment
from campus.hostel.rules import gender_allowed
from campus.tests.factories import make_company
from campus.tests.utils import CampusTestCase

TRUST = "Hostel Test Trust"
COLLEGE_A = "Hostel Test College A"
COLLEGE_B = "Hostel Test College B"
OUTSIDER = "Hostel Test Outsider"


def make_gender(name):
	if not frappe.db.exists("Gender", name):
		frappe.get_doc({"doctype": "Gender", "gender": name}).insert()


def make_role_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Hostel", "send_welcome_email": 0}).insert()
	user = frappe.get_doc("User", email)
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
	user.add_roles(*roles)
	return email


def make_student(first_name, company, gender):
	return frappe.get_doc(
		{
			"doctype": "Student",
			"first_name": first_name,
			"student_email_id": f"{first_name.lower()}@hostel-test.example.com",
			"oc_company": company,
			"gender": gender,
		}
	).insert()


class TestGenderRule(CampusTestCase):
	def test_gender_allowed(self):
		self.assertTrue(gender_allowed("Male", "Male"))
		self.assertTrue(gender_allowed("Female", "Female"))
		self.assertFalse(gender_allowed("Male", "Female"))
		self.assertFalse(gender_allowed("Female", "Male"))
		self.assertFalse(gender_allowed("Male", None))
		self.assertFalse(gender_allowed("", "Male"))


class TestHostelMasters(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name, abbr in ((TRUST, "HTT"), (COLLEGE_A, "HTA"), (COLLEGE_B, "HTB"), (OUTSIDER, "HTO")):
			make_company(name, abbr)
		for gender in ("Male", "Female"):
			make_gender(gender)
		seed_fee_categories()

	def setUp(self):
		frappe.db.savepoint("hostel_masters_test")
		self.addCleanup(frappe.db.rollback, save_point="hostel_masters_test")
		self.agreement = frappe.get_doc(
			{
				"doctype": "Shared Service Agreement",
				"provider_company": TRUST,
				"service": "Hostel",
				"from_date": add_days(today(), -30),
				"members": [{"company": COLLEGE_A}, {"company": COLLEGE_B}],
			}
		).insert()
		self.boys = self.make_hostel("Test Boys Hostel", "Male")
		self.room = self.make_room(self.boys, "G", "101")

	# fixtures
	def make_hostel(self, name, gender, company=TRUST):
		return frappe.get_doc({"doctype": "Hostel", "hostel_name": name, "company": company, "gender": gender}).insert()

	def make_room(self, hostel, floor_name, room_no, room_type="Double"):
		block_name = f"B-{floor_name}"
		if not frappe.db.exists("Hostel Block", f"{hostel.name}-{block_name}"):
			frappe.get_doc({"doctype": "Hostel Block", "hostel": hostel.name, "block_name": block_name}).insert()
		floor_id = f"{hostel.name}-{block_name}-{floor_name}"
		floor = frappe.get_doc("Hostel Floor", floor_id) if frappe.db.exists("Hostel Floor", floor_id) else frappe.get_doc(
			{"doctype": "Hostel Floor", "block": f"{hostel.name}-{block_name}", "floor_name": floor_name}
		).insert()
		if not frappe.db.exists("Hostel Room Type", room_type):
			frappe.get_doc({"doctype": "Hostel Room Type", "room_type_name": room_type}).insert()
		return frappe.get_doc(
			{"doctype": "Hostel Room", "floor": floor.name, "room_no": room_no, "room_type": room_type}
		).insert()

	def capacity(self, room=None):
		return frappe.db.get_value("Hostel Room", (room or self.room).name, "capacity")

	# hostel
	def test_hostel_needs_hostel_agreement_as_provider(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_hostel("Outsider Hostel", "Male", company=OUTSIDER)

	def test_served_colleges_from_agreement(self):
		self.assertEqual(served_colleges(self.boys.name), [COLLEGE_A, COLLEGE_B])

	def test_expired_agreement_serves_nobody(self):
		self.agreement.db_set("to_date", add_days(today(), -1))
		self.assertEqual(served_colleges(self.boys.name), [])

	def test_gender_cannot_change_once_saved(self):
		hostel = frappe.get_doc("Hostel", self.boys.name)
		hostel.gender = "Female"
		with self.assertRaises(frappe.CannotChangeConstantError):
			hostel.save()

	def test_hostel_and_room_get_asset_locations(self):
		hostel = frappe.get_doc("Hostel", self.boys.name)
		room = frappe.get_doc("Hostel Room", self.room.name)
		self.assertTrue(hostel.asset_location)
		self.assertTrue(room.asset_location)
		self.assertEqual(frappe.db.get_value("Location", room.asset_location, "parent_location"), hostel.asset_location)

	# capacity and beds
	def test_capacity_equals_active_beds(self):
		self.assertEqual(self.capacity(), 0)
		add_beds(self.room.name, 3)
		self.assertEqual(self.capacity(), 3)
		bed = frappe.get_doc("Hostel Bed", f"{self.room.name}-2")
		bed.is_active = 0
		bed.save()
		self.assertEqual(self.capacity(), 2)
		bed.is_active = 1
		bed.save()
		self.assertEqual(self.capacity(), 3)

	def test_deleting_a_bed_lowers_capacity(self):
		add_beds(self.room.name, 2)
		frappe.delete_doc("Hostel Bed", f"{self.room.name}-1")
		self.assertEqual(self.capacity(), 1)

	def test_add_beds_continues_numbering(self):
		add_beds(self.room.name, 2)
		self.assertEqual(add_beds(self.room.name, 2), [f"{self.room.name}-3", f"{self.room.name}-4"])

	def test_capacity_cannot_be_typed_in(self):
		add_beds(self.room.name, 2)
		room = frappe.get_doc("Hostel Room", self.room.name)
		room.capacity = 9
		room.save()
		self.assertEqual(self.capacity(), 2)

	def test_bed_without_room_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Hostel Bed", "bed_no": "1"}).insert()
		with self.assertRaises(frappe.LinkValidationError):
			frappe.get_doc({"doctype": "Hostel Bed", "room": "No Such Room", "bed_no": "1"}).insert()

	# allotment gate (used by P4-T02)
	def test_allotment_gender_and_college(self):
		boy = make_student("HostelBoy", COLLEGE_A, "Male")
		girl = make_student("HostelGirl", COLLEGE_A, "Female")
		outsider = make_student("HostelOut", OUTSIDER, "Male")
		validate_allotment(self.boys.name, boy.name)
		with self.assertRaises(frappe.ValidationError):
			validate_allotment(self.boys.name, girl.name)
		with self.assertRaises(frappe.ValidationError):
			validate_allotment(self.boys.name, outsider.name)

	def test_female_hostel_refuses_male(self):
		girls = self.make_hostel("Test Girls Hostel", "Female")
		with self.assertRaises(frappe.ValidationError):
			validate_allotment(girls.name, make_student("HostelBoy2", COLLEGE_B, "Male").name)

	def test_disabled_hostel_and_missing_records_refused(self):
		boy = make_student("HostelBoy3", COLLEGE_A, "Male")
		frappe.db.set_value("Hostel", self.boys.name, "disabled", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
			validate_allotment(self.boys.name, boy.name)
		with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
			validate_allotment("No Such Hostel", boy.name)
		frappe.db.set_value("Hostel", self.boys.name, "disabled", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
			validate_allotment(self.boys.name, "No Such Student")

	def test_student_without_college_refused(self):
		student = make_student("HostelNoCollege", COLLEGE_A, "Male")
		frappe.db.set_value("Student", student.name, "oc_company", None)
		with self.assertRaisesRegex(frappe.ValidationError, "no college"):
			validate_allotment(self.boys.name, student.name)

	# lifecycle and immutability
	def test_lapsed_agreement_does_not_block_editing_or_disabling(self):
		self.agreement.db_set("to_date", add_days(today(), -1))
		hostel = frappe.get_doc("Hostel", self.boys.name)
		hostel.disabled = 1
		hostel.save()
		self.assertEqual(frappe.db.get_value("Hostel", self.boys.name, "disabled"), 1)

	def test_hostel_company_and_bed_room_cannot_change(self):
		hostel = frappe.get_doc("Hostel", self.boys.name)
		hostel.company = COLLEGE_A
		with self.assertRaises(frappe.CannotChangeConstantError):
			hostel.save()
		add_beds(self.room.name, 1)
		other = self.make_room(self.boys, "G", "102")
		bed = frappe.get_doc("Hostel Bed", f"{self.room.name}-1")
		bed.room = other.name
		with self.assertRaises(frappe.CannotChangeConstantError):
			bed.save()
		self.assertEqual((self.capacity(), self.capacity(other)), (1, 0))

	def test_room_identity_cannot_change(self):
		room = frappe.get_doc("Hostel Room", self.room.name)
		room.room_no = "999"
		with self.assertRaises(frappe.CannotChangeConstantError):
			room.save()

	def test_room_save_keeps_bed_capacity(self):
		add_beds(self.room.name, 2)
		stale = frappe.get_doc("Hostel Room", self.room.name)
		add_beds(self.room.name, 1)  # a bed commits after the room was loaded
		stale.status = "Under Maintenance"
		stale.save()
		self.assertEqual(self.capacity(), 3)

	def test_room_is_ac_follows_room_type(self):
		frappe.get_doc({"doctype": "Hostel Room Type", "room_type_name": "Double AC", "is_ac": 1}).insert()
		room = self.make_room(self.boys, "G", "103", room_type="Double AC")
		self.assertEqual(room.is_ac, 1)
		self.assertEqual(self.make_room(self.boys, "G", "104", room_type="Double").is_ac, 0)

	def test_deleting_room_and_hostel_removes_locations(self):
		room_location = frappe.db.get_value("Hostel Room", self.room.name, "asset_location")
		hostel_location = frappe.db.get_value("Hostel", self.boys.name, "asset_location")
		frappe.delete_doc("Hostel Room", self.room.name)
		self.assertFalse(frappe.db.exists("Location", room_location))
		self.assertTrue(frappe.db.exists("Location", hostel_location))
		frappe.delete_doc("Hostel Floor", frappe.db.get_value("Hostel Floor", {"hostel": self.boys.name}))
		frappe.delete_doc("Hostel Block", frappe.db.get_value("Hostel Block", {"hostel": self.boys.name}))
		frappe.delete_doc("Hostel", self.boys.name)
		self.assertFalse(frappe.db.exists("Location", hostel_location))

	def test_hostel_with_rooms_cannot_be_deleted(self):
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Hostel", self.boys.name)

	# permissions
	def test_warden_and_accounts_manager_permissions(self):
		user = make_role_user("hostel-roles@example.com", ["Warden"])
		self.assertTrue(frappe.has_permission("Hostel Bed", "create", user=user))
		self.assertTrue(frappe.has_permission("Hostel Room", "write", user=user))
		self.assertTrue(frappe.has_permission("Hostel", "read", user=user))
		self.assertFalse(frappe.has_permission("Hostel", "write", user=user))
		self.assertFalse(frappe.has_permission("Hostel Fee Rate", "write", user=user))
		accounts = make_role_user("hostel-accounts@example.com", ["Accounts Manager"])
		self.assertTrue(frappe.has_permission("Hostel Fee Rate", "create", user=accounts))
		self.assertTrue(frappe.has_permission("Hostel Settings", "write", user=accounts))
		self.assertFalse(frappe.has_permission("Hostel Bed", "create", user=accounts))
		self.assertFalse(frappe.has_permission("Hostel", "read", user=make_role_user("hostel-none@example.com", [])))

	# fee rate
	def make_rate(self, items):
		return frappe.get_doc(
			{
				"doctype": "Hostel Fee Rate", "company": TRUST, "academic_year": self.academic_year(),
				"room_type": "Double", "items": items,
			}
		).insert()

	def academic_year(self):
		name = "Hostel Test AY"
		if not frappe.db.exists("Academic Year", name):
			frappe.get_doc(
				{"doctype": "Academic Year", "academic_year_name": name, "year_start_date": today(), "year_end_date": today()}
			).insert()
		return name

	def test_fee_rate_lookup(self):
		self.make_rate([{"fee_category": "Hostel", "amount": 30000}, {"fee_category": "Caution Deposit", "amount": 5000}])
		self.assertEqual(fee_rate(TRUST, self.academic_year(), "Double"), {"Hostel": 30000, "Caution Deposit": 5000})
		self.assertEqual(fee_rate(TRUST, self.academic_year(), "Single"), {})

	def test_fee_rate_refuses_duplicate_category_and_negative(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_rate([{"fee_category": "Hostel", "amount": 1}, {"fee_category": "Hostel", "amount": 2}])
		with self.assertRaises(frappe.ValidationError):
			self.make_rate([{"fee_category": "Hostel", "amount": -1}])

	def test_fee_rate_unique_per_year_and_type(self):
		self.make_rate([{"fee_category": "Hostel", "amount": 1}])
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_rate([{"fee_category": "Hostel", "amount": 2}])

	# settings
	def test_settings_need_matching_fee_heads(self):
		doc = {"doctype": "Hostel Settings", "company": TRUST, "hostel_fee_category": "Hostel", "caution_deposit_category": "Caution Deposit"}
		frappe.get_doc(doc).insert()
		frappe.db.delete("Hostel Settings", {"company": TRUST})
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({**doc, "hostel_fee_category": "Tuition"}).insert()
