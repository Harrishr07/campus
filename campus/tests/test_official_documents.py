"""M01-08 Official document register: status from validity, superseded chain, 90/30/7 day expiry alerts, company scope."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_days, today

from campus.iqac import official_documents as register
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

COLLEGE, OTHER_COLLEGE = "Official Doc Test College", "Official Doc Test Other College"
READER, OUTSIDER = "official-doc-reader@example.com", "official-doc-outsider@example.com"
PRIVATE_FILE, PUBLIC_FILE = "/private/files/aicte-approval.pdf", "/files/aicte-approval.pdf"
EXPIRING, EXPIRED = "official_document.expiring", "official_document.expired"


class TestDocumentStatus(UnitTestCase):
	def test_a_document_is_active_up_to_and_including_its_last_day(self):
		self.assertEqual(register.document_status("2026-10-22", None, "2026-10-22"), "Active")
		self.assertEqual(register.document_status("2026-10-22", None, "2026-10-21"), "Active")

	def test_a_document_is_expired_the_day_after_its_last_day(self):
		self.assertEqual(register.document_status("2026-10-22", None, "2026-10-23"), "Expired")

	def test_a_superseded_document_stays_superseded_whatever_its_dates(self):
		self.assertEqual(register.document_status("2026-10-22", "OFD-1", "2026-10-21"), "Superseded")
		self.assertEqual(register.document_status("2026-10-22", "OFD-1", "2027-01-01"), "Superseded")


class TestExpiryStage(UnitTestCase):
	def test_alert_days_come_from_a_comma_separated_record_value(self):
		self.assertEqual(register.alert_offsets("7, 90,30"), [90, 30, 7])

	def test_stage_is_a_reminder_only_on_a_configured_day(self):
		stage = lambda days: register.expiry_stage(add_days("2026-10-22", days), "2026-10-22", [90, 30, 7])  # noqa: E731
		self.assertEqual(stage(90), ("reminder", 90))
		self.assertEqual(stage(30), ("reminder", 30))
		self.assertEqual(stage(7), ("reminder", 7))
		self.assertIsNone(stage(89))
		self.assertIsNone(stage(0))  # the last valid day is not past expiry, and not a configured day
		self.assertEqual(stage(-1), ("expired", 1))


class OfficialDocumentCase(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "ODC")
		make_company(OTHER_COLLEGE, "ODO")
		make_user(READER, [COLLEGE])
		make_user(OUTSIDER, [OTHER_COLLEGE])
		for user in (READER, OUTSIDER):
			frappe.get_doc("User", user).add_roles("IQAC Coordinator")

	def setUp(self):
		frappe.db.savepoint("official_docs")
		self.addCleanup(frappe.db.rollback, save_point="official_docs")
		self.addCleanup(frappe.set_user, "Administrator")
		sendmail = patch("frappe.sendmail", return_value=frappe._dict(name="test-mail"))
		sendmail.start()
		self.addCleanup(sendmail.stop)
		from campus.iqac.official_seed import seed_official_register

		seed_official_register()
		self.principal, self.coordinator = self.make_employee("Principal"), self.make_employee("Coordinator")
		self.make_profile(COLLEGE, self.principal, self.coordinator)

	def make_employee(self, name):
		return frappe.get_doc(
			{
				"doctype": "Employee", "first_name": name, "last_name": frappe.generate_hash(length=6), "gender": self.gender(),
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
				"personal_email": f"{frappe.generate_hash(length=8)}@example.com",
			}
		).insert().name  # fmt: skip

	def gender(self):
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		return "Male"

	def make_profile(self, company, principal, coordinator):
		frappe.get_doc(
			{
				"doctype": "Institution Profile",
				"company": company,
				"institution_status": "Autonomous",
				"principal": principal,
				"iqac_coordinator": coordinator,
			}
		).insert()

	def make_document(self, valid_to_in=100, company=COLLEGE, **values):
		return frappe.get_doc(
			{
				"doctype": "Official Document", "company": company, "authority": "AICTE", "document_type": "Approval",
				"reference_no": f"F.No. {frappe.generate_hash(length=6)}", "valid_from": add_days(today(), -365),
				"valid_to": add_days(today(), valid_to_in), "file": PRIVATE_FILE, **values,
			}
		).insert()  # fmt: skip

	def logs(self, document, event_key=None):
		filters = {"reference_doctype": "Official Document", "reference_name": document.name}
		if event_key:
			filters["event_key"] = event_key
		return frappe.get_all("Message Log", filters, ["event_key", "recipient"])


class TestRegister(OfficialDocumentCase):
	def test_status_follows_the_validity_dates_on_save(self):
		self.assertEqual(self.make_document(10).status, "Active")
		self.assertEqual(self.make_document(-1).status, "Expired")

	def test_valid_to_cannot_precede_valid_from(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_document(-400)

	def test_the_file_must_be_private(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_document(file=PUBLIC_FILE)

	def test_a_private_looking_path_that_climbs_out_of_private_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_document(file="/private/../files/aicte-approval.pdf")

	def test_a_program_of_another_company_is_refused(self):
		program = frappe.get_doc(
			{"doctype": "Program", "program_name": "Official Doc Other BE", "oc_company": OTHER_COLLEGE}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			self.make_document(program=program.name)

	def test_a_document_without_a_program_covers_the_institution(self):
		self.assertFalse(self.make_document().program)


class TestSupersededChain(OfficialDocumentCase):
	def test_superseding_marks_the_old_document_and_keeps_it_for_history(self):
		old, new = self.make_document(200), self.make_document(400)
		old.superseded_by = new.name
		old.save()
		self.assertEqual(frappe.db.get_value("Official Document", old.name, "status"), "Superseded")
		self.assertEqual(frappe.db.get_value("Official Document", new.name, "status"), "Active")

	def test_the_chain_runs_from_the_oldest_to_the_current_document(self):
		a, b, c = self.make_document(10), self.make_document(20), self.make_document(30)
		for old, new in ((a, b), (b, c)):
			old.superseded_by = new.name
			old.save()
		self.assertEqual(register.chain(a.name), [a.name, b.name, c.name])
		self.assertEqual(register.chain(b.name), [a.name, b.name, c.name])
		self.assertEqual(register.current(a.name), c.name)
		self.assertEqual(register.current(c.name), c.name)

	def test_a_document_cannot_supersede_itself_or_close_a_loop(self):
		a, b = self.make_document(10), self.make_document(20)
		a.superseded_by = a.name
		with self.assertRaises(frappe.ValidationError):
			a.save()
		a.reload()
		a.superseded_by = b.name
		a.save()
		b.superseded_by = a.name
		with self.assertRaises(frappe.ValidationError):
			b.save()

	def test_the_superseding_document_must_belong_to_the_same_company(self):
		old, other = self.make_document(10), self.make_document(10, company=OTHER_COLLEGE)
		old.superseded_by = other.name
		with self.assertRaises(frappe.ValidationError):
			old.save()

	def test_removing_the_link_makes_the_document_active_or_expired_again(self):
		old, new = self.make_document(10), self.make_document(20)
		old.superseded_by = new.name
		old.save()
		old.superseded_by = None
		old.save()
		self.assertEqual(old.status, "Active")


class TestExpiryAlerts(OfficialDocumentCase):
	def test_alerts_go_out_on_the_90_30_and_7_day_marks_only(self):
		due = {days: self.make_document(days) for days in (90, 30, 7, 60)}
		self.assertEqual(register.send_expiry_alerts(today()), 3)
		for days, expected in ((90, True), (30, True), (7, True), (60, False)):
			self.assertEqual(bool(self.logs(due[days], EXPIRING)), expected, days)

	def test_the_principal_and_the_iqac_coordinator_of_the_company_are_told(self):
		document = self.make_document(30)
		register.send_expiry_alerts(today())
		self.assertEqual(
			{l.recipient.split(":")[-1] for l in self.logs(document, EXPIRING)},
			{self.principal, self.coordinator},
		)

	def test_a_repeat_run_on_the_same_day_does_not_message_twice(self):
		document = self.make_document(30)
		register.send_expiry_alerts(today())
		first = len(self.logs(document))
		register.send_expiry_alerts(today())
		self.assertEqual(len(self.logs(document)), first)

	def test_the_next_mark_is_a_new_alert(self):
		document = self.make_document(30)
		register.send_expiry_alerts(today())
		register.send_expiry_alerts(add_days(today(), 23))  # 7 days left
		self.assertEqual(len(self.logs(document, EXPIRING)), 4)

	def test_the_alert_days_are_a_record_value(self):
		frappe.db.set_single_value("Official Document Setting", "alert_days", "45")
		days_45, days_30 = self.make_document(45), self.make_document(30)
		self.assertEqual(register.send_expiry_alerts(today()), 1)
		self.assertTrue(self.logs(days_45, EXPIRING))
		self.assertFalse(self.logs(days_30, EXPIRING))

	def test_a_superseded_document_is_not_alerted(self):
		old, new = self.make_document(30), self.make_document(400)
		old.superseded_by = new.name
		old.save()
		self.assertEqual(register.send_expiry_alerts(today()), 0)
		self.assertFalse(self.logs(old))

	def test_a_company_without_anyone_to_tell_logs_a_warning_and_the_run_goes_on(self):
		frappe.db.delete("Institution Profile", {"company": COLLEGE})
		self.make_document(30)
		with patch("frappe.logger") as logger:
			self.assertEqual(register.send_expiry_alerts(today()), 1)
		logger.return_value.warning.assert_called_once()

	def test_a_renewal_that_moves_valid_to_is_alerted_again_on_the_same_mark(self):
		document = self.make_document(30)
		register.send_expiry_alerts(today())
		frappe.db.set_value("Official Document", document.name, "valid_to", add_days(today(), 31))
		register.send_expiry_alerts(add_days(today(), 1))  # renewed to a date 30 days after the next run
		self.assertEqual(len(self.logs(document, EXPIRING)), 4)

	def test_a_failed_send_leaves_the_document_active_so_the_next_run_retries(self):
		document = self.make_document(1)
		frappe.db.set_value("Official Document", document.name, "valid_to", add_days(today(), -1))
		with patch("campus.iqac.official_documents.send", side_effect=RuntimeError("down")):
			register.send_expiry_alerts(today())
		self.assertEqual(frappe.db.get_value("Official Document", document.name, "status"), "Active")
		self.assertEqual(register.send_expiry_alerts(today()), 1)
		self.assertEqual(frappe.db.get_value("Official Document", document.name, "status"), "Expired")
		self.assertEqual(len(self.logs(document, EXPIRED)), 2)

	def test_an_active_document_past_its_last_day_becomes_expired_once_and_is_kept(self):
		document = self.make_document(1)
		frappe.db.set_value(
			"Official Document", document.name, "valid_to", add_days(today(), -1)
		)  # time passed since the save
		self.assertEqual(register.send_expiry_alerts(today()), 1)
		self.assertEqual(frappe.db.get_value("Official Document", document.name, "status"), "Expired")
		self.assertEqual(
			{l.recipient.split(":")[-1] for l in self.logs(document, EXPIRED)},
			{self.principal, self.coordinator},
		)
		self.assertEqual(register.send_expiry_alerts(today()), 0)  # already expired: not told again
		self.assertEqual(len(self.logs(document, EXPIRED)), 2)
		self.assertTrue(frappe.db.exists("Official Document", document.name))


class TestCompanyScope(OfficialDocumentCase):
	def test_a_user_sees_only_the_documents_of_their_company(self):
		mine, theirs = self.make_document(), self.make_document(company=OTHER_COLLEGE)
		frappe.set_user(READER)
		names = frappe.get_list("Official Document", pluck="name")
		self.assertIn(mine.name, names)
		self.assertNotIn(theirs.name, names)
		self.assertTrue(frappe.has_permission("Official Document", "read", mine.name))
		self.assertFalse(frappe.has_permission("Official Document", "read", theirs.name))
		frappe.set_user(OUTSIDER)
		self.assertEqual(frappe.get_list("Official Document", pluck="name"), [theirs.name])

	def test_an_outsider_cannot_create_a_document_for_another_company(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			self.make_document(company=COLLEGE)

	def test_staff_without_an_iqac_role_cannot_read_the_register(self):
		document = self.make_document()
		user = "official-doc-plain@example.com"
		make_user(user, [COLLEGE])
		frappe.set_user(user)
		self.assertFalse(frappe.has_permission("Official Document", "read", document.name))


class TestPermissions(OfficialDocumentCase):
	def test_nobody_may_delete_a_document_and_a_principal_works_within_their_company(self):
		meta = frappe.get_meta("Official Document")
		self.assertFalse([p.role for p in meta.permissions if p.delete])
		principal = "official-doc-principal@example.com"
		make_user(principal, [COLLEGE])
		frappe.get_doc("User", principal).add_roles("Principal")
		mine, theirs = self.make_document(), self.make_document(company=OTHER_COLLEGE)
		frappe.set_user(principal)
		self.assertEqual(frappe.get_list("Official Document", pluck="name"), [mine.name])
		self.assertTrue(frappe.has_permission("Official Document", "write", mine.name))
		self.assertFalse(frappe.has_permission("Official Document", "read", theirs.name))
		self.assertFalse(frappe.has_permission("Official Document", "delete", mine.name))
