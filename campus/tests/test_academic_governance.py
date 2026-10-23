"""P2-T01 (M02-01) tests: the composition rule logic (unit), and Body Type / Body / External Member behaviour
(integration): AC1 a Governing Body without a university nominee is refused with the rule shown, AC2 a member is
left out of the counts after the end date, AC3 the compliance report lists the violating bodies."""

import frappe
from frappe.model import get_permitted_fields
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.academic_governance import api, composition
from campus.academic_governance.report.body_composition_compliance import body_composition_compliance as report
from campus.academic_governance.seed import NON_STATUTORY, STATUTORY, seed_body_types
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE, OTHER_COLLEGE = "Governance Test College", "Governance Other College"
GOVERNING_BODY = "Governing Body"


def member(category, from_date="2026-01-01", to_date=None):
	return frappe._dict(category=category, from_date=from_date, to_date=to_date)


def rule(category, minimum=0, maximum=0, mandatory=0):
	return frappe._dict(category=category, minimum_count=minimum, maximum_count=maximum, mandatory_for_quorum=mandatory)


class TestCompositionRules(UnitTestCase):
	def test_term_is_inclusive_of_both_ends(self):
		term = member("Internal", "2026-03-01", "2026-03-31")
		self.assertFalse(composition.in_office(term, "2026-02-28"))
		self.assertTrue(composition.in_office(term, "2026-03-01"))
		self.assertTrue(composition.in_office(term, "2026-03-31"))
		self.assertFalse(composition.in_office(term, "2026-04-01"))

	def test_open_term_stays_in_office(self):
		self.assertTrue(composition.in_office(member("Internal"), "2040-01-01"))

	def test_expired_and_future_members_are_not_counted(self):
		members = [member("Alumni"), member("Alumni", to_date="2026-05-31"), member("Alumni", from_date="2026-09-01")]
		self.assertEqual(composition.count_by_category(members, "2026-06-15"), {"Alumni": 1})
		self.assertEqual(composition.count_by_category(members, "2026-05-31"), {"Alumni": 2})

	def test_rule_met_has_no_shortfall(self):
		members = [member("University Nominee")]
		self.assertEqual(composition.composition_shortfalls([rule("University Nominee", 1)], members, "2026-06-15"), [])

	def test_below_minimum(self):
		(shortfall,) = composition.composition_shortfalls([rule("University Nominee", 2)], [member("University Nominee")], "2026-06-15")
		self.assertEqual((shortfall.category, shortfall.minimum, shortfall.actual), ("University Nominee", 2, 1))
		self.assertIn("at least 2 University Nominee", shortfall.message)
		self.assertIn("1 in office", shortfall.message)

	def test_above_maximum(self):
		members = [member("Student")] * 3
		(shortfall,) = composition.composition_shortfalls([rule("Student", 0, 2)], members, "2026-06-15")
		self.assertEqual((shortfall.maximum, shortfall.actual, shortfall.rule), (2, 3, "0 to 2 Student"))

	def test_zero_maximum_is_no_limit(self):
		self.assertEqual(composition.composition_shortfalls([rule("Student", 1)], [member("Student")] * 9, "2026-06-15"), [])

	def test_exactly_n_wording(self):
		(shortfall,) = composition.composition_shortfalls([rule("University Nominee", 3, 3)], [], "2026-06-15")
		self.assertEqual(shortfall.rule, "exactly 3 University Nominee")

	def test_missing_category_counts_zero_and_each_broken_rule_reports(self):
		rules = [rule("Alumni", 1), rule("External Expert", 1), rule("Student", 0, 5)]
		shortfalls = composition.composition_shortfalls(rules, [member("External Expert")], "2026-06-15")
		self.assertEqual([s.category for s in shortfalls], ["Alumni"])

	def test_mandatory_quorum_categories(self):
		rules = [rule("University Nominee", 1, 0, 1), rule("Student", 1)]
		self.assertEqual(composition.mandatory_quorum_categories(rules), ["University Nominee"])


class TestBodies(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "GTC")
		make_company(OTHER_COLLEGE, "GOC")

	def setUp(self):
		frappe.db.savepoint("governance_test")
		self.addCleanup(frappe.db.rollback, save_point="governance_test")
		seed_body_types()

	def employee(self, company=COLLEGE):
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Gov",
				"last_name": frappe.generate_hash(length=6),
				"gender": "Male",
				"date_of_birth": "1980-01-01",
				"date_of_joining": "2010-01-01",
				"company": company,
			}
		).insert()
		return doc.name

	def external(self, name="Prof Visitor", **values):
		return frappe.get_doc({"doctype": "External Member", "member_name": name, **values}).insert().name

	def body(self, members, body_type=GOVERNING_BODY, company=COLLEGE, **values):
		doc = {"doctype": "Body", "body_name": f"Test {body_type}", "company": company, "body_type": body_type, "members": members, **values}
		return frappe.get_doc(doc)

	def nominee(self, **dates):
		return {"category": "University Nominee", "external_member": self.external(), "from_date": add_days(today(), -30), **dates}

	def internal(self, **dates):
		return {"category": "Internal", "employee": self.employee(), "from_date": add_days(today(), -30), **dates}

	# AC1
	def test_governing_body_without_university_nominee_is_refused_with_the_rule(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.body([self.internal()]).insert()
		message = str(caught.exception)
		self.assertIn("at least 1 University Nominee", message)
		self.assertIn(GOVERNING_BODY, message)

	def test_governing_body_with_university_nominee_saves(self):
		doc = self.body([self.internal(), self.nominee()]).insert()
		self.assertEqual(doc.name, f"Test {GOVERNING_BODY} - GTC")
		self.assertEqual([m.member_name for m in doc.members][0][:3], "Gov")

	def test_nominee_whose_term_ended_fails_the_rule(self):
		with self.assertRaises(frappe.ValidationError):
			self.body([self.nominee(to_date=add_days(today(), -1))]).insert()

	def test_disabled_body_is_not_checked(self):
		self.assertTrue(self.body([self.internal()], enabled=0).insert().name)

	def test_academic_council_needs_at_least_three_nominees(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.body([self.nominee(), self.nominee()], "Academic Council").insert()
		self.assertIn("at least 3 University Nominee", str(caught.exception))
		self.body([self.nominee(), self.nominee(), self.nominee()], "Academic Council").insert()
		self.body([self.nominee() for _ in range(4)], "Academic Council", body_name="Four Nominees").insert()  # no upper limit is sourced

	# editing and drafting
	def lapsed_body(self, **values):
		"""A saved Governing Body that breaks its rule today (inserted disabled, then enabled)."""
		doc = self.body([self.internal()], enabled=0, **values).insert()
		doc.db_set("enabled", 1)
		return frappe.get_doc("Body", doc.name)

	def warnings(self):
		return " ".join(str(m) for m in frappe.local.message_log).lower()

	def test_editing_a_body_that_already_breaks_the_rule_saves_with_a_warning(self):
		doc = self.lapsed_body()
		frappe.clear_messages()
		doc.append("members", self.internal())
		doc.save()
		self.assertIn("composition", self.warnings())

	def test_an_edit_that_makes_a_breach_worse_is_refused(self):
		doc = self.body([self.nominee(), self.internal()]).insert()
		doc.members[0].to_date = add_days(today(), -1)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_body_drafted_with_future_dated_terms_saves(self):
		start = add_days(today(), 20)
		rows = [{**self.nominee(), "from_date": start}, {**self.internal(), "from_date": start}]
		self.assertTrue(self.body(rows).insert().name)

	def test_an_empty_body_saves_as_a_draft_with_a_warning(self):
		frappe.clear_messages()
		self.assertTrue(self.body([]).insert().name)
		self.assertIn("composition", self.warnings())

	def test_row_without_from_date_is_a_mandatory_error_not_a_crash(self):
		row = {"category": "University Nominee", "external_member": self.external()}
		with self.assertRaises(frappe.MandatoryError):
			self.body([row], enabled=0).insert()

	def test_a_left_employee_cannot_be_a_current_member(self):
		employee = self.employee()
		frappe.db.set_value("Employee", employee, "status", "Left")
		row = {"category": "Internal", "employee": employee, "from_date": add_days(today(), -30)}
		with self.assertRaises(frappe.ValidationError):
			self.body([row, self.nominee()]).insert()
		ended = {**row, "to_date": add_days(today(), -1)}
		self.body([ended, self.nominee()]).insert()  # a finished term in the past is history

	# AC2
	def test_member_is_excluded_from_the_count_after_the_end_date(self):
		ends = add_days(today(), 10)
		doc = self.body([self.internal(), self.nominee(to_date=ends)]).insert()
		on_last_day = [m.category for m in api.members_in_office(doc.name, ends)]
		after = [m.category for m in api.members_in_office(doc.name, add_days(ends, 1))]
		self.assertEqual(sorted(on_last_day), ["Internal", "University Nominee"])
		self.assertEqual(after, ["Internal"])
		self.assertEqual(api.composition_shortfalls(doc.name, ends), [])
		(shortfall,) = api.composition_shortfalls(doc.name, add_days(ends, 1))
		self.assertEqual((shortfall.category, shortfall.actual), ("University Nominee", 0))

	def test_quorum_mandatory_categories_come_from_the_body_type(self):
		self.assertEqual(api.quorum_mandatory_categories(GOVERNING_BODY), ["University Nominee"])
		self.assertEqual(api.quorum_mandatory_categories("Academic Council"), [])

	def test_member_row_needs_exactly_one_person(self):
		both = {**self.nominee(), "employee": self.employee()}
		neither = {"category": "Internal", "from_date": today()}
		for row in (both, neither):
			with self.assertRaises(frappe.ValidationError):
				self.body([row, self.nominee()]).insert()

	def test_employee_must_belong_to_the_body_company(self):
		row = {**self.internal(), "employee": self.employee(OTHER_COLLEGE)}
		with self.assertRaises(frappe.ValidationError):
			self.body([row, self.nominee()]).insert()

	def test_term_dates_and_overlap(self):
		person = self.external("Repeat Visitor")
		one = {"category": "University Nominee", "external_member": person, "from_date": "2026-01-01", "to_date": "2026-06-30"}
		with self.assertRaises(frappe.ValidationError):  # To before From
			self.body([{**one, "to_date": "2025-12-31"}], enabled=0).insert()
		with self.assertRaises(frappe.ValidationError):  # same person twice at once
			self.body([one, {**one, "from_date": "2026-06-30", "to_date": None}], enabled=0).insert()
		self.body([one, {**one, "from_date": "2026-07-01", "to_date": None}], enabled=0).insert()  # re-appointed after the term

	# Body Type
	def test_seeded_body_types_hold_only_sourced_rules(self):
		governing = frappe.get_doc("Body Type", GOVERNING_BODY)
		self.assertEqual((governing.statutory, governing.term_years, governing.min_meetings_per_year, governing.quorum_percent), (1, 5, 2, 50))
		self.assertEqual([(r.category, r.minimum_count, r.maximum_count, r.mandatory_for_quorum) for r in governing.composition], [("University Nominee", 1, 0, 1)])
		council = frappe.get_doc("Body Type", "Academic Council")
		self.assertEqual([(r.category, r.minimum_count, r.maximum_count) for r in council.composition], [("University Nominee", 3, 0)])
		for name in ("Board of Studies", "Finance Committee", *NON_STATUTORY):
			body_type = frappe.get_doc("Body Type", name)
			self.assertEqual((body_type.composition, body_type.quorum_percent, body_type.min_meetings_per_year), ([], 0, 0), name)
		for name, *_rest in STATUTORY:
			self.assertEqual(frappe.db.get_value("Body Type", name, "statutory"), 1, name)
		for name in NON_STATUTORY:
			self.assertEqual(frappe.db.get_value("Body Type", name, "statutory"), 0, name)

	def test_unsourced_seed_values_are_reverted_only_when_unedited(self):
		from campus.academic_governance.seed import revert_unsourced_values

		board = frappe.get_doc("Body Type", "Board of Studies")
		board.quorum_percent = 50
		board.min_meetings_per_year = 2
		board.term_years = 3
		board.append("composition", {"category": "External Expert", "minimum_count": 1})
		board.append("composition", {"category": "Alumni", "minimum_count": 1})
		board.save()
		finance = frappe.get_doc("Body Type", "Finance Committee")
		finance.quorum_percent = 40  # an edit: not the old seed
		finance.save()
		revert_unsourced_values()
		board.reload()
		self.assertEqual((board.composition, board.quorum_percent, board.min_meetings_per_year, board.term_years), ([], 0, 0, 0))
		self.assertEqual(frappe.db.get_value("Body Type", "Finance Committee", "quorum_percent"), 40)

	def test_seed_is_idempotent_and_keeps_edits(self):
		frappe.db.set_value("Body Type", GOVERNING_BODY, "quorum_percent", 60)
		count = frappe.db.count("Body Type")
		seed_body_types()
		self.assertEqual(frappe.db.count("Body Type"), count)
		self.assertEqual(frappe.db.get_value("Body Type", GOVERNING_BODY, "quorum_percent"), 60)

	def test_body_type_rejects_bad_rules(self):
		def make(rows):
			return frappe.get_doc({"doctype": "Body Type", "body_type_name": "Bad Rules", "composition": rows}).insert()

		with self.assertRaises(frappe.ValidationError):  # repeated category
			make([{"category": "Student", "minimum_count": 1}, {"category": "Student", "minimum_count": 2}])
		with self.assertRaises(frappe.ValidationError):  # max below min
			make([{"category": "Student", "minimum_count": 3, "maximum_count": 2}])
		with self.assertRaises(frappe.ValidationError):  # mandatory but no minimum
			make([{"category": "Student", "mandatory_for_quorum": 1}])

	def test_body_category_options_match_the_rule_categories(self):
		options = lambda doctype: frappe.get_meta(doctype).get_field("category").options
		self.assertEqual(options("Body Member"), options("Body Type Composition Rule"))

	# External Member
	def member_doc(self, **values):
		return {"doctype": "External Member", "member_name": "Pan Person", "organisation": "Anna University", "expertise": "Maths", **values}

	def supplier_member(self, name="Supplier Person", **supplier_values):
		member = frappe.get_doc("External Member", self.external(name))
		supplier = member.create_supplier()
		if supplier_values:
			frappe.db.set_value("Supplier", supplier, supplier_values)
		return frappe.get_doc("External Member", member.name), supplier

	def test_pan_and_bank_are_read_from_the_supplier_and_never_stored(self):
		member, supplier = self.supplier_member(pan="ABCDE1234F")
		self.assertEqual(member.pan, "ABCDE1234F")
		self.assertFalse(member.bank_account)
		if frappe.db.has_column("External Member", "pan"):
			self.assertFalse(frappe.db.sql("select pan from `tabExternal Member` where name=%s", member.name)[0][0])
		self.assertTrue(member.meta.get_field("pan").is_virtual)

	def test_the_suppliers_default_bank_account_is_shown(self):
		if not frappe.db.exists("Bank", "Governance Test Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "Governance Test Bank"}).insert()
		member, supplier = self.supplier_member("Bank Person")
		account = frappe.get_doc(
			{"doctype": "Bank Account", "account_name": "Bank Person", "bank": "Governance Test Bank", "party_type": "Supplier", "party": supplier, "is_default": 1}
		).insert()
		self.assertEqual(member.bank_account, account.name)

	def test_pan_and_bank_fields_are_restricted_to_accounts_and_principal(self):
		def readable(role):
			user = f"gov-{role.replace(' ', '-').lower()}@example.com"
			make_user(user, [COLLEGE])
			frappe.get_doc("User", user).add_roles(role)
			return set(get_permitted_fields("External Member", user=user))

		for role in ("Accounts User", "Principal"):
			self.assertTrue({"pan", "bank_account"} <= readable(role), role)
		for role in ("Dean Academics", "HOD"):
			fields = readable(role)
			self.assertTrue({"member_name", "organisation", "expertise"} <= fields, role)
			self.assertTrue(not {"pan", "bank_account"} & fields, role)
		self.assertFalse(frappe.get_meta("External Member").track_changes)

	def test_create_supplier_links_without_copying_other_fields(self):
		member, supplier = self.supplier_member()
		self.assertEqual(member.supplier, supplier)
		self.assertEqual(frappe.db.get_value("Supplier", supplier, "supplier_name"), "Supplier Person")
		with self.assertRaises(frappe.ValidationError):
			member.create_supplier()

	def test_a_supplier_belongs_to_one_external_member(self):
		member, supplier = self.supplier_member()
		other = frappe.get_doc("External Member", self.external("Other Person"))
		other.supplier = supplier
		with self.assertRaises(frappe.ValidationError):
			other.save()

	def test_existing_pan_moves_to_the_supplier_once(self):
		from campus.academic_governance.external_member_pan import move_stored_pan_to_suppliers

		if not frappe.db.has_column("External Member", "pan"):  # a test cannot add it (DDL commits)
			self.skipTest("only sites created before PAN became virtual (7123735) have the stored pan column to move")
		linked, supplier = self.supplier_member("Linked Person")
		blocked, other_supplier = self.supplier_member("Filled Person", pan="ZZZZZ9999Z")
		unlinked = frappe.get_doc("External Member", self.external("Unlinked Person"))
		for member, pan in ((linked, "ABCDE1234F"), (blocked, "ABCDE1234G"), (unlinked, "ABCDE1234H")):
			frappe.db.sql("update `tabExternal Member` set pan=%s where name=%s", (pan, member.name))
		move_stored_pan_to_suppliers()
		self.assertEqual(frappe.db.get_value("Supplier", supplier, "pan"), "ABCDE1234F")
		self.assertEqual(frappe.db.get_value("Supplier", other_supplier, "pan"), "ZZZZZ9999Z")  # never overwritten
		unlinked.reload()
		self.assertTrue(unlinked.supplier)
		self.assertEqual(frappe.db.get_value("Supplier", unlinked.supplier, "pan"), "ABCDE1234H")
		for member in (linked, blocked, unlinked):
			self.assertFalse(frappe.db.sql("select pan from `tabExternal Member` where name=%s", member.name)[0][0])

	# AC3
	def violating_body(self, name, **values):
		doc = self.body([self.internal()], body_name=name, enabled=0, **values).insert()
		doc.db_set("enabled", 1)
		return doc.name

	def test_report_lists_violations_across_bodies(self):
		bad = self.violating_body("Bad Governing Body")
		bad_council = self.violating_body("Bad Council", body_type="Academic Council")
		good = self.body([self.nominee()], body_name="Good Governing Body").insert().name
		rows = {(r["body"], r["category"]): r for r in report.execute({"company": COLLEGE})[1]}
		self.assertEqual(set(rows), {(bad, "University Nominee"), (bad_council, "University Nominee")})
		self.assertEqual(rows[(bad, "University Nominee")]["rule"], "at least 1 University Nominee")
		self.assertEqual(rows[(bad_council, "University Nominee")]["in_office"], 0)
		self.assertNotIn(good, {r["body"] for r in rows.values()})

	def test_report_filters_by_body_type_and_date(self):
		compliant = self.body([self.nominee(to_date=add_days(today(), 5))], body_name="Soon Lapsing").insert().name
		self.assertEqual(report.execute({"company": COLLEGE})[1], [])
		later = report.execute({"company": COLLEGE, "as_on_date": add_days(today(), 6)})[1]
		self.assertEqual([r["body"] for r in later], [compliant])
		self.assertEqual(report.execute({"company": COLLEGE, "as_on_date": add_days(today(), 6), "body_type": "Academic Council"})[1], [])

	def test_report_ignores_other_companies_and_needs_a_company(self):
		self.violating_body("Bad Governing Body")
		self.assertEqual(report.execute({"company": OTHER_COLLEGE})[1], [])
		self.assertEqual(report.execute({})[1], [])

	def test_report_respects_user_permissions(self):
		self.violating_body("Bad Governing Body")
		user = "gov-report@example.com"
		make_user(user, [OTHER_COLLEGE])
		frappe.get_doc("User", user).add_roles("Dean Academics")
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(report.execute({"company": COLLEGE})[1], [])
