"""P1-T14 tests (M04-01, M04-02, M04-04): Verhoeff, masking, eligibility per category, Aadhaar at rest."""

import frappe
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import UnitTestCase

from campus.admissions import eligibility as elig
from campus.admissions.aadhaar import is_valid_aadhaar, mask, verhoeff_valid
from campus.admissions.api import evaluate_eligibility, reveal_aadhaar
from campus.tests.factories import make_company, make_user
from campus.tests.test_regulation import make_program, make_regulation, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE = "Admissions Test College"
PROGRAM = "Admissions Test BE"
VIEWER, PLAIN = "aadhaar-viewer@example.com", "aadhaar-plain@example.com"
OTHER_COLLEGE, OTHER_VIEWER = "Admissions Other College", "aadhaar-other@example.com"
SUBJECTS = "Mathematics\nPhysics\nChemistry"


def with_check_digit(body):
	return next(body + str(d) for d in range(10) if verhoeff_valid(body + str(d)))


VALID = with_check_digit("23412341234")
INVALID = VALID[:-1] + str((int(VALID[-1]) + 1) % 10)


class TestAadhaarUnit(UnitTestCase):
	def test_known_verhoeff_vector(self):
		self.assertTrue(verhoeff_valid("2363"))  # standard Verhoeff example
		self.assertFalse(verhoeff_valid("2364"))

	def test_valid_and_invalid_numbers(self):
		self.assertTrue(is_valid_aadhaar(VALID))
		self.assertTrue(is_valid_aadhaar(f"{VALID[:4]} {VALID[4:8]}-{VALID[8:]}"))
		self.assertFalse(is_valid_aadhaar(INVALID))
		self.assertFalse(is_valid_aadhaar(VALID[:-1]))  # 11 digits
		self.assertFalse(is_valid_aadhaar("ABCDEFGHIJKL"))

	def test_leading_zero_or_one_rejected_even_with_good_checksum(self):
		for lead in "01":
			self.assertFalse(is_valid_aadhaar(with_check_digit(lead + "3412341234")))

	def test_mask_shows_last_four_only(self):
		self.assertEqual(mask(VALID), f"XXXX-XXXX-{VALID[-4:]}")
		self.assertNotIn(VALID[:8], mask(VALID))


class TestEligibilityUnit(UnitTestCase):
	REQUIRED = ["Mathematics", "Physics", "Chemistry"]
	MINIMUMS = {"OC": 50.0, "BC": 45.0, "SC": 40.0}

	def marks(self, m, p, c):
		return [("Mathematics", 100, m), ("physics", 100, p), ("Chemistry", 100, c)]

	def check(self, marks, category, required=None):
		return elig.check_eligibility(self.REQUIRED if required is None else required, self.MINIMUMS, marks, category, "HSC")

	def test_passes_at_exact_minimum(self):
		self.assertEqual(self.check(self.marks(50, 50, 50), "OC"), [])

	def test_below_minimum_for_category_fails_with_reason(self):
		reasons = self.check(self.marks(49, 49, 49), "OC")
		self.assertEqual(len(reasons), 1)
		self.assertIn("49.00%", reasons[0])
		self.assertIn("OC", reasons[0])

	def test_same_marks_pass_for_lower_threshold_category(self):
		self.assertEqual(self.check(self.marks(46, 46, 46), "BC"), [])
		self.assertEqual(self.check(self.marks(41, 41, 41), "SC"), [])
		self.assertNotEqual(self.check(self.marks(41, 41, 41), "BC"), [])

	def test_missing_subject_is_reported(self):
		reasons = self.check([("Mathematics", 100, 90), ("Physics", 100, 90)], "OC")
		self.assertTrue(any("Chemistry" in r for r in reasons))

	def test_no_marks_and_no_category(self):
		self.assertEqual(len(self.check([], "OC")), 1)
		self.assertTrue(any("category" in r for r in self.check(self.marks(90, 90, 90), None)))

	def test_category_without_row_has_no_minimum_and_no_subjects_uses_all_rows(self):
		self.assertEqual(self.check(self.marks(1, 1, 1), "ST"), [])
		self.assertEqual(elig.check_eligibility([], self.MINIMUMS, [("Any", 200, 100)], "OC"), [])
		self.assertNotEqual(elig.check_eligibility([], self.MINIMUMS, [("Any", 200, 99)], "OC"), [])


class TestAdmissionsIntegration(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "ATC")
		make_program(PROGRAM, COLLEGE)
		make_year("2022")
		cls.regulation = make_regulation("R2022", COLLEGE, [PROGRAM], "2022").name
		make_company(OTHER_COLLEGE, "ATO")
		for user in (VIEWER, PLAIN):
			make_user(user, [COLLEGE])
		make_user(OTHER_VIEWER, [OTHER_COLLEGE])
		frappe.get_doc("User", OTHER_VIEWER).add_roles("Aadhaar Viewer", "Academics User")
		frappe.get_doc("User", VIEWER).add_roles("Aadhaar Viewer", "Academics User")
		frappe.get_doc("User", PLAIN).add_roles("System Manager")
		for dt in ("Student Category",):
			for cat in ("OC", "BC"):
				if not frappe.db.exists(dt, cat):
					frappe.get_doc({"doctype": dt, "category": cat}).insert()
		frappe.db.delete("Student Applicant", {"program": PROGRAM})
		frappe.db.delete("Eligibility Rule", {"program": PROGRAM})
		frappe.get_doc(
			{
				"doctype": "Eligibility Rule", "program": PROGRAM, "qualifying_exam": "HSC",
				"required_subjects": SUBJECTS,
				"category_marks": [
					{"student_category": "OC", "min_percent": 50},
					{"student_category": "BC", "min_percent": 45},
				],
			}
		).insert()  # fmt: skip

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def applicant(self, aadhaar=None, category="OC", marks=(60, 60, 60)):
		return frappe.get_doc(
			{
				"doctype": "Student Applicant", "first_name": "Admit", "program": PROGRAM,
				"student_email_id": f"admit-{frappe.generate_hash(length=8)}@example.com", "oc_company": COLLEGE,
				"student_category": category, "oc_aadhaar": aadhaar, "academic_year": year_name("2022"),
				"oc_qualifying_marks": [
					{"subject": s, "max_marks": 100, "obtained_marks": m}
					for s, m in zip(SUBJECTS.splitlines(), marks, strict=True)
				],
			}
		).insert()  # fmt: skip

	# Aadhaar
	def test_invalid_checksum_rejected_without_echoing_number(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.applicant(INVALID)
		self.assertNotIn(INVALID, str(ctx.exception))

	def test_valid_number_encrypted_at_rest_masked_everywhere_else(self):
		doc = self.applicant(VALID)
		column = frappe.db.sql("select oc_aadhaar from `tabStudent Applicant` where name=%s", doc.name)[0][0]
		self.assertNotIn(VALID, column)
		self.assertEqual(set(column), {"*"})
		stored = frappe.db.sql(
			"select password from __Auth where doctype='Student Applicant' and name=%s and fieldname='oc_aadhaar'",
			doc.name,
		)[0][0]
		self.assertNotIn(VALID, stored)  # ciphertext
		self.assertEqual(frappe.db.get_value("Student Applicant", doc.name, "oc_aadhaar_masked"), f"XXXX-XXXX-{VALID[-4:]}")
		reloaded = frappe.get_doc("Student Applicant", doc.name)
		self.assertNotIn(VALID, frappe.as_json(reloaded.as_dict()))
		self.assertNotIn(VALID, frappe.as_json(frappe.client.get("Student Applicant", doc.name)))
		self.assertNotIn(VALID, frappe.as_json(frappe.get_list("Student Applicant", fields=["oc_aadhaar", "oc_aadhaar_masked"])))
		html = frappe.get_print("Student Applicant", doc.name)
		self.assertNotIn(VALID, html)
		self.assertNotIn(VALID[:8], html)

	def test_resave_keeps_number_and_mask_and_client_cannot_forge_mask(self):
		doc = self.applicant(VALID)
		doc = frappe.get_doc("Student Applicant", doc.name)
		doc.oc_aadhaar_masked = "XXXX-XXXX-0000"
		doc.save()
		self.assertEqual(doc.oc_aadhaar_masked, f"XXXX-XXXX-{VALID[-4:]}")
		self.assertEqual(doc.get_password("oc_aadhaar"), VALID)

	def test_student_has_the_same_field(self):
		student = frappe.get_doc(
			{"doctype": "Student", "first_name": "Aadhaar", "student_email_id": f"aadhaar-student-{frappe.generate_hash(length=8)}@example.com",
			 "oc_company": COLLEGE, "oc_aadhaar": VALID}
		).insert()  # fmt: skip
		self.assertEqual(student.oc_aadhaar_masked, f"XXXX-XXXX-{VALID[-4:]}")
		self.assertEqual(student.get_password("oc_aadhaar"), VALID)

	def test_reveal_denied_without_role_and_not_logged(self):
		doc = self.applicant(VALID)
		before = frappe.db.count("Aadhaar Access Log")
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.PermissionError):
			reveal_aadhaar("Student Applicant", doc.name)
		self.assertEqual(frappe.db.count("Aadhaar Access Log"), before)

	def test_get_password_cannot_bypass_the_role(self):
		doc = self.applicant(VALID)
		frappe.set_user(PLAIN)  # System Manager but not Aadhaar Viewer
		# the dotted path the request handler would run for frappe.client.get_password
		method = frappe.get_attr(frappe.get_hooks("override_whitelisted_methods")["frappe.client.get_password"][-1])
		with self.assertRaises(frappe.PermissionError):
			method("Student Applicant", doc.name, "oc_aadhaar")

	def test_reveal_by_viewer_returns_number_and_logs(self):
		doc = self.applicant(VALID)
		frappe.set_user(VIEWER)
		self.assertEqual(reveal_aadhaar("Student Applicant", doc.name), VALID)
		log = frappe.get_all(
			"Aadhaar Access Log", filters={"reference_name": doc.name},
			fields=["user", "reference_doctype", "accessed_on"],
		)  # fmt: skip
		self.assertEqual([(r.user, r.reference_doctype) for r in log], [(VIEWER, "Student Applicant")])
		self.assertTrue(log[0].accessed_on)

	# eligibility
	def test_eligibility_stored_on_applicant(self):
		ok = self.applicant(marks=(60, 60, 60))
		self.assertEqual(evaluate_eligibility(ok.name), {"eligible": True, "reasons": []})
		self.assertEqual(frappe.db.get_value("Student Applicant", ok.name, "oc_eligibility_status"), "Eligible")

	def test_ineligible_with_reasons_per_category(self):
		low_oc = self.applicant(category="OC", marks=(46, 46, 46))
		result = evaluate_eligibility(low_oc.name)
		self.assertFalse(result["eligible"])
		self.assertIn("50", result["reasons"][0])
		self.assertEqual(frappe.db.get_value("Student Applicant", low_oc.name, "oc_eligibility_status"), "Ineligible")
		self.assertIn("50", frappe.db.get_value("Student Applicant", low_oc.name, "oc_eligibility_reasons"))
		self.assertTrue(evaluate_eligibility(self.applicant(category="BC", marks=(46, 46, 46)).name)["eligible"])

	def test_no_rule_for_program_is_not_eligible(self):
		frappe.db.set_value("Eligibility Rule", {"program": PROGRAM}, "enabled", 0)
		try:
			result = evaluate_eligibility(self.applicant().name)
		finally:
			frappe.db.set_value("Eligibility Rule", {"program": PROGRAM}, "enabled", 1)
		self.assertFalse(result["eligible"])

	# masters
	def test_refund_rule_rejects_overlap_and_bad_percent(self):
		def rule(*slabs):
			return frappe.get_doc({"doctype": "Refund Rule", "company": COLLEGE, "slabs": [
				{"days_from_admission_start": a, "days_to_admission_start": b, "deduction_percent": p} for a, b, p in slabs]})  # fmt: skip

		rule((0, 10, 0), (11, 30, 10)).insert()
		with self.assertRaises(frappe.ValidationError):
			rule((0, 10, 0), (10, 30, 10)).insert()
		with self.assertRaises(frappe.ValidationError):
			rule((0, 10, 120)).insert()

	def test_counselling_authority_mapping_targets_must_exist(self):
		def authority(target):
			return frappe.get_doc({"doctype": "Counselling Authority", "authority_name": "Test Authority",
				"column_mapping": [{"source_column": "Rank", "target_field": target}]})  # fmt: skip

		frappe.db.delete("Counselling Authority", {"authority_name": "Test Authority"})
		with self.assertRaises(frappe.ValidationError):
			authority("no_such_field").insert()
		authority("oc_rank").insert()

	# review fixes
	def test_reveal_endpoints_are_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[reveal_aadhaar], ["POST"])
		doc = self.applicant(VALID)
		method = frappe.get_attr(frappe.get_hooks("override_whitelisted_methods")["frappe.client.get_password"][-1])
		frappe.set_user(VIEWER)
		with patch.object(frappe.local, "request", SimpleNamespace(method="GET"), create=True):
			with self.assertRaises(frappe.PermissionError):
				method("Student Applicant", doc.name, "oc_aadhaar")
		with patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True):
			self.assertEqual(method("Student Applicant", doc.name, "oc_aadhaar"), VALID)

	def test_reveal_log_is_marked_for_commit_and_carries_ip(self):
		doc = self.applicant(VALID)
		frappe.local.flags.commit = False
		frappe.set_user(VIEWER)
		reveal_aadhaar("Student Applicant", doc.name)
		self.assertTrue(frappe.local.flags.commit)
		frappe.local.flags.commit = False

	def test_jinja_get_password_is_gated_and_logged(self):
		doc = self.applicant(VALID)
		template = "{{ doc.get_password('oc_aadhaar') }}"
		frappe.set_user(PLAIN)
		with self.assertRaises(frappe.PermissionError):
			frappe.render_template(template, {"doc": frappe.get_doc("Student Applicant", doc.name)})
		frappe.set_user(VIEWER)
		before = frappe.db.count("Aadhaar Access Log", {"reference_name": doc.name})
		self.assertEqual(frappe.render_template(template, {"doc": frappe.get_doc("Student Applicant", doc.name)}), VALID)
		self.assertEqual(frappe.db.count("Aadhaar Access Log", {"reference_name": doc.name}), before + 1)
		frappe.local.flags.commit = False

	def test_other_password_fields_still_readable_by_system_manager(self):
		name = "Admissions Pwd Test"
		frappe.db.delete("Connected App", {"name": name})
		app = frappe.get_doc(
			{"doctype": "Connected App", "provider_name": name, "client_id": "cid", "client_secret": "s3cret",
			 "authorization_uri": "https://example.com/a", "token_uri": "https://example.com/t",
			 "scopes": [{"scope": "read"}]}
		).insert()  # fmt: skip
		frappe.set_user(PLAIN)
		method = frappe.get_attr(frappe.get_hooks("override_whitelisted_methods")["frappe.client.get_password"][-1])
		self.assertEqual(method("Connected App", app.name, "client_secret"), "s3cret")

	def test_viewer_of_another_company_is_denied(self):
		doc = self.applicant(VALID)
		frappe.set_user(OTHER_VIEWER)
		with self.assertRaises(frappe.PermissionError):
			reveal_aadhaar("Student Applicant", doc.name)

	def test_access_log_cannot_be_deleted(self):
		doc = self.applicant(VALID)
		frappe.set_user(VIEWER)
		reveal_aadhaar("Student Applicant", doc.name)
		frappe.set_user("Administrator")
		log = frappe.get_last_doc("Aadhaar Access Log", {"reference_name": doc.name})
		with self.assertRaises(frappe.PermissionError):
			log.delete()

	def test_rule_with_matching_regulation_wins_and_duplicates_rejected(self):
		blank = frappe.db.get_value("Eligibility Rule", {"program": PROGRAM, "enabled": 1})
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Eligibility Rule", "program": PROGRAM, "qualifying_exam": "HSC"}).insert()
		self.assertEqual(elig.find_rule(PROGRAM, "No Such Regulation").name, blank)  # falls back to blank
		specific = frappe.get_doc(
			{"doctype": "Eligibility Rule", "program": PROGRAM, "qualifying_exam": "HSC", "regulation": self.regulation}
		).insert()
		self.assertEqual(elig.find_rule(PROGRAM, self.regulation).name, specific.name)
		self.assertEqual(elig.find_rule(PROGRAM).name, blank)
