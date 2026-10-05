"""P1-T17 tests (M04-05): web form -> Lead -> WhatsApp acknowledgement -> round-robin -> Applicant, follow-ups, funnel."""

import json
from unittest.mock import MagicMock

import frappe
from frappe.utils import add_days, nowdate
from frappe.website.doctype.web_form.web_form import accept

from campus.admissions import enquiry, enquiry_followup
from campus.admissions.api import convert_lead_to_applicant
from campus.admissions.report.enquiry_funnel_by_source import enquiry_funnel_by_source as funnel
from campus.tests.factories import make_company, make_user
from campus.tests.test_messaging import adapters
from campus.tests.test_regulation import make_program, make_year, year_name
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Enquiry Test College", "ETC"
BARE_COLLEGE = "Enquiry Bare College"  # no Institution Profile
PROGRAM = "Enquiry Test BA"
OFFICER_A, OFFICER_B = "enquiry-a@example.com", "enquiry-b@example.com"
OUTSIDER = "enquiry-outsider@example.com"
MOBILE = "9876543210"


def submit_web_form(company=COLLEGE, **values):
	data = {"company": company, "lead_name": "Priya Lakshmi Raman", "mobile_no": MOBILE, "email_id": f"priya{len(frappe.get_all('Lead'))}@example.com",
		"oc_program_interest": PROGRAM, **values}  # fmt: skip
	frappe.set_user("Guest")
	try:
		accept(web_form="admission-enquiry", data=json.dumps(data))
	finally:
		frappe.set_user("Administrator")
	return frappe.get_last_doc("Lead", {"mobile_no": data["mobile_no"], "company": company}) if company else None


def assignee(lead):
	return frappe.db.get_value("ToDo", {"reference_type": "Lead", "reference_name": lead.name, "status": "Open"}, "allocated_to")


class EnquiryTestCase(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, ABBR)
		make_company(BARE_COLLEGE, "EBC")
		if not frappe.db.exists("Institution Profile", {"company": COLLEGE}):
			frappe.get_doc({"doctype": "Institution Profile", "company": COLLEGE}).insert()
		make_program(PROGRAM, COLLEGE)
		make_year("2026")
		for user in (OFFICER_A, OFFICER_B):
			make_user(user, [COLLEGE])
			frappe.get_doc("User", user).add_roles("Admission Officer")
		make_user(OUTSIDER, [BARE_COLLEGE])
		frappe.get_doc("User", OUTSIDER).add_roles("Admission Officer")

	def setUp(self):
		self.clear_enquiries()
		frappe.cache.delete(frappe.cache.make_key("oc-enquiry-rate-unknown"))
		self.whatsapp = MagicMock(return_value="wa-1")
		patcher = adapters(whatsapp=self.whatsapp)
		patcher.start()
		self.addCleanup(patcher.stop)

	@staticmethod
	def clear_enquiries():
		"""Tests share one transaction per class, so each starts from no enquiries and a fresh round robin."""
		leads = frappe.get_all("Lead", {"company": ("in", (COLLEGE, BARE_COLLEGE))}, pluck="name")
		for table, field in (("ToDo", "reference_name"), ("Message Log", "reference_name")):
			frappe.db.delete(table, {field: ("in", leads)})
		frappe.db.delete("Student Applicant", {"oc_lead": ("in", leads)})
		frappe.db.delete("Lead", {"name": ("in", leads)})
		for rule in frappe.get_all("Assignment Rule", {"name": ("like", enquiry.RULE_PREFIX + "%")}, pluck="name"):
			frappe.delete_doc("Assignment Rule", rule, force=True)
		frappe.clear_cache()

	def make_lead(self, **values):
		return frappe.get_doc(
			{"doctype": "Lead", "lead_name": "Ravi Kumar", "mobile_no": MOBILE, "company": COLLEGE, "oc_program_interest": PROGRAM, **values}
		).insert()


class TestWebEnquiry(EnquiryTestCase):
	def test_web_enquiry_creates_lead_acknowledges_and_assigns(self):
		lead = submit_web_form()
		self.assertEqual((lead.company, lead.oc_program_interest, lead.utm_source), (COLLEGE, PROGRAM, enquiry.WEB_FORM_SOURCE))
		self.whatsapp.assert_called_once()
		log = frappe.get_all("Message Log", {"reference_name": lead.name}, ["event_key", "channel", "address", "status"])
		self.assertEqual([(r.event_key, r.channel, r.address) for r in log], [(enquiry.ACK_EVENT, "whatsapp", "+91" + MOBILE)])
		self.assertIn(assignee(lead), (OFFICER_A, OFFICER_B))

	def test_round_robin_alternates_between_officers_and_ignores_other_colleges(self):
		first, second, third = (submit_web_form(mobile_no=f"98765432{n:02d}") for n in (10, 11, 12))
		assigned = [assignee(lead) for lead in (first, second, third)]
		self.assertEqual(set(assigned[:2]), {OFFICER_A, OFFICER_B})
		self.assertEqual(assigned[2], assigned[0])
		self.assertNotIn(OUTSIDER, assigned)

	def test_resaving_does_not_reassign_or_resend(self):
		lead = submit_web_form()
		owner = assignee(lead)
		for _ in range(2):
			lead.reload().save()
		self.assertEqual(assignee(lead), owner)
		self.assertEqual(frappe.db.count("ToDo", {"reference_type": "Lead", "reference_name": lead.name}), 1)
		self.assertEqual(frappe.db.count("Message Log", {"reference_name": lead.name}), 1)
		self.assertEqual(enquiry.send(enquiry.ACK_EVENT, lead, [f"phone:+91{MOBILE}"]), frappe.get_all("Message Log", {"reference_name": lead.name}, pluck="name"))

	def test_desk_lead_without_program_interest_is_left_alone(self):
		lead = self.make_lead(oc_program_interest=None)
		self.whatsapp.assert_not_called()
		self.assertIsNone(assignee(lead))

	def test_program_of_another_college_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_lead(company=BARE_COLLEGE)

	def test_number_without_a_usable_mobile_sends_nothing(self):
		lead = self.make_lead(mobile_no=None, phone="044-2345678")
		self.whatsapp.assert_not_called()
		self.assertIsNotNone(lead.name)

	def test_phone_normalisation(self):
		doc = frappe._dict
		self.assertEqual(enquiry.whatsapp_number(doc(mobile_no="98765 43210")), "+919876543210")
		self.assertEqual(enquiry.whatsapp_number(doc(mobile_no="+91 98765-43210")), "+919876543210")
		self.assertEqual(enquiry.whatsapp_number(doc(mobile_no="09876543210")), "+919876543210")
		self.assertEqual(enquiry.whatsapp_number(doc(mobile_no="1234", whatsapp_no="9876543210")), "+919876543210")
		self.assertIsNone(enquiry.whatsapp_number(doc(mobile_no="12345")))

	def test_officer_changes_update_the_rule(self):
		submit_web_form()
		name = enquiry.RULE_PREFIX + COLLEGE
		self.assertEqual([u.user for u in frappe.get_doc("Assignment Rule", name).users], [OFFICER_A, OFFICER_B])
		frappe.db.set_value("User", OFFICER_A, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "User", OFFICER_A, "enabled", 1)
		enquiry.sync_assignment_rule(COLLEGE)
		self.assertEqual([u.user for u in frappe.get_doc("Assignment Rule", name).users], [OFFICER_B])


class TestSpamGuard(EnquiryTestCase):
	def test_honeypot_blocks_submission(self):
		with self.assertRaises(frappe.ValidationError):
			submit_web_form(oc_website_url="http://spam.example")
		self.assertFalse(frappe.db.exists("Lead", {"mobile_no": MOBILE, "company": COLLEGE}))

	def test_company_without_institution_profile_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			submit_web_form(company=BARE_COLLEGE, oc_program_interest=None)

	def test_guest_is_rate_limited(self):
		for n in range(enquiry.GUEST_LIMIT):
			submit_web_form(mobile_no=f"97654321{n:02d}")
		with self.assertRaises(frappe.RateLimitExceededError):
			submit_web_form(mobile_no="9765432199")
		frappe.cache.delete(frappe.cache.make_key("oc-enquiry-rate-unknown"))


class TestConversion(EnquiryTestCase):
	def test_split_name(self):
		self.assertEqual(enquiry.split_name("Priya"), ("Priya", "", ""))
		self.assertEqual(enquiry.split_name("Priya Raman"), ("Priya", "", "Raman"))
		self.assertEqual(enquiry.split_name(" Priya  Lakshmi  Raman "), ("Priya", "Lakshmi", "Raman"))
		self.assertEqual(enquiry.split_name(""), ("", "", ""))

	def test_convert_copies_contact_and_program_and_links_back(self):
		lead = self.make_lead(lead_name="Priya Lakshmi Raman", email_id="priya@example.com")
		name = convert_lead_to_applicant(lead.name, year_name("2026"))
		applicant = frappe.get_doc("Student Applicant", name)
		self.assertEqual((applicant.first_name, applicant.middle_name, applicant.last_name), ("Priya", "Lakshmi", "Raman"))
		self.assertEqual((applicant.student_mobile_number, applicant.student_email_id), (MOBILE, "priya@example.com"))
		self.assertEqual((applicant.program, applicant.oc_company, applicant.oc_lead), (PROGRAM, COLLEGE, lead.name))
		lead.reload()
		self.assertEqual((lead.oc_applicant, lead.status), (name, "Converted"))

	def test_second_conversion_returns_the_same_applicant(self):
		lead = self.make_lead()
		first = convert_lead_to_applicant(lead.name, year_name("2026"))
		self.assertEqual(convert_lead_to_applicant(lead.name, year_name("2026")), first)
		self.assertEqual(frappe.db.count("Student Applicant", {"oc_lead": lead.name}), 1)

	def test_conversion_needs_a_program(self):
		lead = self.make_lead(oc_program_interest=None)
		with self.assertRaises(frappe.ValidationError):
			convert_lead_to_applicant(lead.name, year_name("2026"))

	def test_default_academic_year_is_used_when_none_is_given(self):
		lead = self.make_lead()
		name = convert_lead_to_applicant(lead.name)
		self.assertEqual(frappe.db.get_value("Student Applicant", name, "academic_year"), enquiry.default_academic_year())


class TestFollowUps(EnquiryTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Enquiry Follow-up Rule", {"company": COLLEGE})
		self.rule = frappe.get_doc(
			{"doctype": "Enquiry Follow-up Rule", "company": COLLEGE, "days_after": 2, "message": "Call {{ doc.lead_name }} about {{ doc.oc_program_interest }}"}
		).insert()

	def aged_lead(self, days, **values):
		lead = self.make_lead(**values)
		frappe.db.set_value("Lead", lead.name, "creation", f"{add_days(nowdate(), -days)} 10:00:00", update_modified=False)
		return lead

	def todos(self, lead):
		return frappe.get_all("ToDo", {"reference_name": lead.name, "oc_followup_rule": self.rule.name}, ["allocated_to", "description"])

	def test_reminder_goes_to_the_assigned_officer_once(self):
		lead = self.aged_lead(3)
		owner = assignee(lead)
		self.assertEqual(len(enquiry_followup.create_due_todos()), 1)
		enquiry_followup.create_due_todos()
		todos = self.todos(lead)
		self.assertEqual(len(todos), 1)
		self.assertEqual(todos[0].allocated_to, owner)
		self.assertEqual(todos[0].description, f"Call Ravi Kumar about {PROGRAM}")

	def test_young_converted_and_unassigned_leads_get_no_reminder(self):
		young = self.aged_lead(0)
		converted = self.aged_lead(5, mobile_no="9000000001")
		frappe.db.set_value("Lead", converted.name, "status", "Converted")
		unassigned = self.aged_lead(5, mobile_no="9000000002", company=BARE_COLLEGE, oc_program_interest=None)
		enquiry_followup.create_due_todos()
		for lead in (young, converted, unassigned):
			self.assertEqual(self.todos(lead), [])

	def test_disabled_rule_creates_nothing(self):
		lead = self.aged_lead(5)
		frappe.db.set_value("Enquiry Follow-up Rule", self.rule.name, "enabled", 0)
		enquiry_followup.create_due_todos()
		self.assertEqual(self.todos(lead), [])

	def test_rule_validation(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Enquiry Follow-up Rule", "company": COLLEGE, "days_after": 0, "message": "x"}).insert()
		with self.assertRaises(frappe.ValidationError):  # duplicate day
			frappe.get_doc({"doctype": "Enquiry Follow-up Rule", "company": COLLEGE, "days_after": 2, "message": "y"}).insert()


class TestFunnelReport(EnquiryTestCase):
	def test_counts_per_source(self):
		frappe.get_doc({"doctype": "UTM Source", "name": "Enquiry Test Fair"}).insert() if not frappe.db.exists("UTM Source", "Enquiry Test Fair") else None
		web = submit_web_form()
		fair = [self.make_lead(mobile_no=f"90000000{n}", utm_source="Enquiry Test Fair") for n in range(3)]
		frappe.db.set_value("Lead", fair[0].name, "status", "Open")
		applicant = convert_lead_to_applicant(fair[1].name, year_name("2026"))
		frappe.db.set_value("Student Applicant", applicant, "application_status", "Admitted")
		convert_lead_to_applicant(web.name, year_name("2026"))
		_cols, rows = funnel.execute({"company": COLLEGE})
		by_source = {r["source"]: r for r in rows}
		self.assertEqual({k: by_source["Enquiry Test Fair"][k] for k in ("leads", "contacted", "applicants", "admitted")}, {"leads": 3, "contacted": 2, "applicants": 1, "admitted": 1})
		self.assertEqual({k: by_source[enquiry.WEB_FORM_SOURCE][k] for k in ("leads", "contacted", "applicants", "admitted")}, {"leads": 1, "contacted": 1, "applicants": 1, "admitted": 0})

	def test_company_is_required_and_scoped(self):
		with self.assertRaises(frappe.ValidationError):
			funnel.execute({})
		frappe.set_user(OFFICER_A)
		try:
			self.assertEqual(funnel.execute({"company": BARE_COLLEGE})[1], [])
		finally:
			frappe.set_user("Administrator")
