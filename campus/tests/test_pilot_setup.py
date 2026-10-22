"""PR-02 tests: the pilot setup kit builds a college from its profile once, re-runs change nothing, every role user
has its roles and company permission and can log in, and an inconsistent profile is refused before anything is written."""

import copy
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import check_password

from campus.campus_platform.doctype.regulation.regulation import regulation_name
from campus.setup import fees, people
from campus.setup.admission import largest_remainder
from campus.setup.pilot import setup_college
from campus.setup.profile import PROFILE_DIR, load_profile, profile_errors

SXCCE = json.loads((PROFILE_DIR / "sxcce.json").read_text())
COUNTED = (
	"Company", "Department", "Program", "Academic Year", "Academic Term", "Regulation", "Exam Rule Set", "Seat Matrix",
	"Fee Structure", "Approval Policy", "User", "User Permission", "Employee", "Instructor", "Position Holder",
	"Student", "Guardian", "Student Group", "Shared Service Agreement", "Institution Profile", "Admission Quota",
)  # fmt: skip


def counts():
	return {doctype: frappe.db.count(doctype) for doctype in COUNTED}


def other_college():
	"""A second college from the same code: only data differs."""
	profile = copy.deepcopy(SXCCE)
	profile["name"] = "other"
	profile["trust"] = {"name": "Other Pilot Trust", "abbr": "OPT"}
	profile["college"].update(name="Other Pilot Engineering College", abbr="OPEC")
	profile["user_domain"] = "other.example.edu"
	profile["programmes"] = [dict(p, name="B.E. CSE (OPEC)") for p in profile["programmes"] if p["abbr"] == "CSE"]
	profile["regulation"]["programmes"] = ["B.E. CSE (OPEC)"]
	profile["fees"]["programmes"] = ["B.E. CSE (OPEC)"]
	profile["class_group"]["programme"] = "B.E. CSE (OPEC)"
	profile["college"]["leaders"] = {"principal": "principal"}
	profile["class_group"]["name"] = "OPEC B.E. CSE 2026-27 A"
	profile["users"] = [u for u in profile["users"] if u["key"] in ("office", "principal", "student", "guardian")]
	for user in profile["users"]:
		user["position"] = user.get("position") if user["key"] == "principal" else None
		if not user["position"]:
			del user["position"]
	profile["approval_policies"] = []
	return profile


class TestPilotSetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.first = setup_college("sxcce", test_passwords=True)
		cls.after_first = counts()
		cls.second = setup_college("sxcce", test_passwords=True)
		cls.college = SXCCE["college"]["name"]

	def test_second_run_creates_and_updates_nothing(self):
		self.assertEqual(self.second["created"], {})
		self.assertEqual(self.second["updated"], {})
		self.assertEqual(counts(), self.after_first)

	def test_first_run_built_the_structure(self):
		self.assertTrue(frappe.db.exists("Company", self.college))
		self.assertEqual(frappe.db.get_value("Company", self.college, "parent_company"), SXCCE["trust"]["name"])
		self.assertEqual(frappe.db.count("Program", {"oc_company": self.college}), 6)
		self.assertEqual(frappe.db.get_value("Program", "B.Tech IT", "program_abbreviation"), "IT")
		abbr = SXCCE["college"]["abbr"]
		for department in SXCCE["departments"]:
			self.assertTrue(frappe.db.exists("Department", f"{department} - {abbr}"), department)

	def test_institution_profile_is_autonomous_under_anna_university(self):
		profile = frappe.get_doc("Institution Profile", self.college)
		self.assertEqual(
			(profile.institution_status, profile.affiliating_university, profile.examination_mode),
			("Autonomous", "Anna University", "Autonomous"),
		)
		for field, key in (("principal", "principal"), ("coe", "coe"), ("iqac_coordinator", "iqac")):
			user = f"{key}@{SXCCE['user_domain']}"
			self.assertEqual(profile.get(field), frappe.db.get_value("Employee", {"user_id": user}))

	def test_regulation_is_effective_with_its_rules(self):
		name = regulation_name("R2022", self.college)
		regulation = frappe.get_doc("Regulation", name)
		self.assertEqual(regulation.status, "Effective")
		self.assertEqual(sorted(row.program for row in regulation.programs), sorted(p["name"] for p in SXCCE["programmes"]))
		for doctype in ("Exam Rule Set", "Grading Scheme", "Classification Rule", "Curriculum Rule", "Registration Rule", "Attendance Rule"):
			self.assertTrue(frappe.db.exists(doctype, {"regulation": name}), doctype)
		# the exam values are the seeded R2022 ones (CIA 40 / ESE 60 for theory), not new ones
		theory = frappe.get_doc("Exam Rule Set", {"regulation": name}).types[0]
		self.assertEqual((theory.course_type, theory.cia_max, theory.ese_max), ("Theory", 40, 60))

	def test_seat_matrix_sums_to_the_programme_intake(self):
		for programme in SXCCE["programmes"]:
			matrix = frappe.get_doc("Seat Matrix", {"company": self.college, "program": programme["name"], "academic_year": "2026-27"})
			self.assertEqual(sum(row.sanctioned for row in matrix.rows), programme["intake"])
		gq = frappe.get_doc("Seat Matrix", {"company": self.college, "program": "B.E. CSE"}).rows
		self.assertEqual(sum(r.sanctioned for r in gq if r.quota == "GQ"), 39)  # 65% of 60

	def test_fee_structures_per_programme_and_quota_are_submitted(self):
		structures = frappe.get_all("Fee Structure", {"company": self.college}, ["name", "docstatus", "oc_admission_quota", "total_amount"])
		self.assertEqual(len(structures), 12)
		self.assertTrue(all(s.docstatus == 1 for s in structures))
		self.assertEqual({s.oc_admission_quota for s in structures}, {None, "MQ"})

	def test_a_fresh_site_gets_the_standard_selling_price_list_for_confirm_joining(self):
		frappe.db.set_single_value("Selling Settings", "selling_price_list", "")
		fees.ensure_selling_defaults()
		self.assertEqual(frappe.db.get_single_value("Selling Settings", "selling_price_list"), "Standard Selling")
		self.assertEqual(frappe.db.get_value("Price List", "Standard Selling", ["currency", "selling", "enabled"]), ("INR", 1, 1))

	def test_a_price_list_the_college_already_chose_is_kept(self):
		frappe.db.set_single_value("Selling Settings", "selling_price_list", "Standard Selling")
		with patch.object(frappe.db, "set_single_value") as write:
			fees.ensure_selling_defaults()
		write.assert_not_called()

	def test_every_company_of_the_kit_has_a_holiday_list_with_sundays_off(self):
		trust, college = frappe.db.get_value("Company", self.college, "parent_company"), self.college
		lists = {frappe.db.get_value("Company", company, "default_holiday_list") for company in (trust, college)}
		self.assertEqual(len(lists), 1)
		holiday_list = lists.pop()
		self.assertTrue(holiday_list)
		self.assertTrue(frappe.db.exists("Holiday List", {"name": holiday_list, "weekly_off": "Sunday"}))
		self.assertTrue(frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": "2026-07-05"}))  # a Sunday

	def test_wizard_fixtures_the_company_needs_are_installed(self):
		self.assertTrue(frappe.db.exists("Warehouse Type", "Transit"))

	def test_trust_provides_hostel_and_transport(self):
		for service in ("Hostel", "Transport"):
			agreement = frappe.get_doc("Shared Service Agreement", {"provider_company": SXCCE["trust"]["name"], "service": service})
			self.assertEqual([m.company for m in agreement.members], [self.college])

	def test_core_path_policies_exist(self):
		for document_type in ("Certificate Request", "Result Ratification", "Rejoin Application", "Fee Refund", "Fee Concession"):
			self.assertTrue(frappe.db.exists("Approval Policy", {"document_type": document_type}), document_type)

	def test_every_role_user_can_log_in_with_its_roles_and_company(self):
		for spec in SXCCE["users"]:
			user = f"{spec['key']}@{SXCCE['user_domain']}"
			self.assertEqual(frappe.db.get_value("User", user, "enabled"), 1, user)
			self.assertEqual(check_password(user, SXCCE["test_password"]), user)
			held = set(frappe.get_roles(user))
			self.assertTrue(set(spec["roles"]) <= held, f"{user}: {set(spec['roles']) - held}")
			companies = set(frappe.get_all("User Permission", {"user": user, "allow": "Company"}, pluck="for_value"))
			expected = {self.college if t == "college" else SXCCE["trust"]["name"] for t in spec["companies"]}
			self.assertEqual(companies, expected, user)

	def test_position_holders_and_pilot_student(self):
		domain = SXCCE["user_domain"]
		hod_department = f"Computer Science and Engineering - {SXCCE['college']['abbr']}"
		self.assertEqual(frappe.db.get_value("Position Holder", {"position": "HOD", "scope_value": hod_department}, "user"), f"hod@{domain}")
		self.assertEqual(frappe.db.get_value("Position Holder", {"position": "PRINCIPAL", "scope_value": self.college}, "user"), f"principal@{domain}")
		student = frappe.get_doc("Student", {"student_email_id": f"student@{domain}"})
		self.assertEqual(student.user, f"student@{domain}")
		self.assertEqual([g.guardian for g in student.guardians], [frappe.db.get_value("Guardian", {"email_address": f"guardian@{domain}"})])

	def test_a_changed_profile_value_updates_the_record(self):
		profile = copy.deepcopy(SXCCE)
		profile["programmes"][0]["intake"] = 120
		try:
			result = setup_college(profile, test_passwords=True)
			self.assertEqual(frappe.db.get_value("Program", "B.E. CSE", "oc_sanctioned_intake"), 120)
			self.assertEqual(result["updated"]["Program"], 1)
			self.assertEqual(result["updated"]["Seat Matrix"], 1)
			self.assertEqual(result["created"], {})
		finally:
			setup_college("sxcce", test_passwords=True)  # the class shares its data: put the profile's values back


class TestPilotProfile(IntegrationTestCase):
	def test_the_shipped_profile_is_sound(self):
		self.assertEqual(profile_errors(SXCCE), [])
		self.assertEqual(load_profile("sxcce")["college"]["abbr"], "SXCCE")

	def test_unknown_programme_in_the_regulation_is_refused(self):
		profile = copy.deepcopy(SXCCE)
		profile["regulation"]["programmes"].append("B.E. Aerospace")
		self.assertTrue(any("B.E. Aerospace" in e for e in profile_errors(profile)))
		counted = counts()
		with self.assertRaises(frappe.ValidationError):
			setup_college(profile, test_passwords=True)
		self.assertEqual(counts(), counted)

	def test_missing_college_is_refused(self):
		profile = copy.deepcopy(SXCCE)
		del profile["college"]["abbr"]
		with self.assertRaises(frappe.ValidationError):
			setup_college(profile, test_passwords=True)

	def test_seat_rules_are_checked_before_any_write(self):
		for change, fragment in (
			(lambda p: p["seats"]["quotas"][0].update(share_pct=60), "add up to 100"),
			(lambda p: p["seats"]["split"].pop("MQ"), "no category split"),
			(lambda p: p["seats"].update(academic_year="1999-00"), "1999-00"),
		):
			profile = copy.deepcopy(SXCCE)
			change(profile)
			self.assertIn(fragment, " ".join(profile_errors(profile)))

	def test_references_are_validated_up_front(self):
		profile = copy.deepcopy(SXCCE)
		profile["class_group"]["programme"] = "Nope"
		profile["college"]["leaders"]["coe"] = "office"
		del profile["users"][0]["roles"]
		profile["users"][1]["position"] = {"code": "HOD", "scope": "group"}
		profile["class_group"] = None
		errors = " ".join(profile_errors(profile))
		for fragment in ("needs a key, a name and roles", "no employee record", "no class group"):
			self.assertIn(fragment, errors)

	def test_test_passwords_flag_is_parsed_strictly(self):
		from campus.setup.pilot import parse_flag

		self.assertEqual([parse_flag(v) for v in (None, True, "false", "Yes", "0")], [None, True, False, True, False])
		with self.assertRaises(frappe.ValidationError):
			parse_flag("maybe")

	def test_other_inconsistencies_are_named(self):
		profile = copy.deepcopy(SXCCE)
		profile["programmes"][0]["department"] = "Astrology"
		profile["fees"]["programmes"] = ["Nope"]
		profile["seats"]["split"]["GQ"]["XX"] = 1
		profile["users"][0]["companies"] = ["moon"]
		profile["regulation"]["code"] = "R1999"
		errors = " ".join(profile_errors(profile))
		for fragment in ("Astrology", "Nope", "XX", "moon", "R1999"):
			self.assertIn(fragment, errors)

	def test_unknown_profile_name_or_path_is_refused(self):
		for name in ("nope", "../sxcce", "sxcce.json"):
			with self.assertRaises(frappe.ValidationError):
				load_profile(name)

	def test_an_unknown_role_stops_the_run_before_writing(self):
		profile = copy.deepcopy(SXCCE)
		profile["users"][0]["roles"] = ["No Such Role"]
		counted = counts()
		with self.assertRaises(frappe.ValidationError):
			setup_college(profile, test_passwords=True)
		self.assertEqual(counts(), counted)

	def test_largest_remainder_adds_up(self):
		self.assertEqual(largest_remainder(60, {"a": 31, "b": 30, "c": 20, "d": 18, "e": 1}), {"a": 19, "b": 18, "c": 12, "d": 11, "e": 0})
		self.assertEqual(sum(largest_remainder(39, {"a": 31, "b": 30, "c": 20, "d": 18, "e": 1}).values()), 39)
		self.assertEqual(largest_remainder(5, {}), {})


class TestPilotPasswords(IntegrationTestCase):
	def test_test_passwords_are_refused_on_a_real_site(self):
		with patch.object(people, "test_passwords_allowed", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				setup_college(other_college(), test_passwords=True)

	def test_a_real_site_stores_no_password_and_returns_reset_links(self):
		with patch.object(people, "test_passwords_allowed", return_value=False):
			result = setup_college(other_college())
		self.assertEqual(sorted(result["reset_links"]), sorted(f"{k}@other.example.edu" for k in ("office", "principal", "student", "guardian")))
		user = "office@other.example.edu"
		self.assertTrue(result["reset_links"][user].startswith("http"))
		with self.assertRaises(frappe.AuthenticationError):
			check_password(user, SXCCE["test_password"])

	def test_a_programme_of_another_college_is_refused_and_untouched(self):
		setup_college("sxcce", test_passwords=True)
		profile = other_college()
		profile["programmes"][0]["name"] = "B.E. CSE"
		profile["regulation"]["programmes"] = ["B.E. CSE"]
		with self.assertRaises(frappe.ValidationError):
			setup_college(profile, test_passwords=True)
		self.assertEqual(frappe.db.get_value("Program", "B.E. CSE", "oc_company"), SXCCE["college"]["name"])

	def test_a_difference_on_an_effective_regulation_is_reported(self):
		setup_college("sxcce", test_passwords=True)
		name = regulation_name("R2022", SXCCE["college"]["name"])
		rule = frappe.db.get_value("Attendance Rule", {"regulation": name})
		frappe.db.set_value("Attendance Rule", rule, "condonation_fee", 900)
		notes = setup_college("sxcce", test_passwords=True)["notes"]
		self.assertTrue(any("Attendance Rule" in n and "differs" in n for n in notes), notes)

	def test_a_second_college_needs_no_code_change(self):
		result = setup_college(other_college(), test_passwords=True)
		self.assertEqual(result["college"], "Other Pilot Engineering College")
		self.assertEqual(frappe.db.count("Program", {"oc_company": "Other Pilot Engineering College"}), 1)
		self.assertEqual(setup_college(other_college(), test_passwords=True)["created"], {})
