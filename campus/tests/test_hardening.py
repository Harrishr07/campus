"""PR-05 Production hardening: the permission matrix rules and the site checklist."""

import csv
import os
import tempfile
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from campus.setup import permission_matrix as matrix
from campus.setup import site_check


def row(name, role, **flags):
	return {"kind": "DocType", "name": name, "role": role, "permlevel": 0, **flags}


def report_row(name, role, ref_doctype, **flags):
	return {
		"kind": "Report",
		"name": name,
		"role": role,
		"permlevel": 0,
		"read": 1,
		"ref_doctype": ref_doctype,
		**flags,
	}


class TestPermissionRules(IntegrationTestCase):
	"""Each rule against synthetic rows: it flags the breach and passes the allowed case."""

	def defects(self, *rows, restricted=()):
		return matrix.find_defects(list(rows), list(restricted))

	def test_only_system_manager_deletes_history(self):
		self.assertEqual(self.defects(row("Student Result", "System Manager", delete=1)), [])
		self.assertEqual(
			self.defects(row("Student Result", "COE", delete=1)),
			["Student Result: COE can delete a record kept for history"],
		)
		self.assertEqual(
			self.defects(row("Fine Rule", "Accounts Manager", delete=1)), []
		)  # not kept for history

	def test_student_facing_roles_read_only_listed_doctypes(self):
		self.assertEqual(self.defects(row("Student Result", "Student", read=1, portal=1)), [])
		self.assertEqual(
			self.defects(row("Seat Override Log", "Guardian", read=1, portal=1)),
			["Seat Override Log: Guardian can read a staff-only DocType"],
		)
		self.assertEqual(len(self.defects(row("Circular", "Guest", read=1, write=0))), 0)

	def test_history_includes_submittable_doctypes_unless_exempt(self):
		self.assertEqual(
			self.defects(row("New Ledger", "Accounts Manager", delete=1, submittable=1)),
			["New Ledger: Accounts Manager can delete a record kept for history"],
		)
		self.assertEqual(self.defects(row("New Ledger", "Accounts Manager", delete=1)), [])  # draft-only
		with patch.object(matrix, "HISTORY_EXEMPT", ("New Ledger",)):
			self.assertEqual(self.defects(row("New Ledger", "Accounts Manager", delete=1, submittable=1)), [])

	def test_any_role_without_desk_access_is_student_facing(self):
		self.assertEqual(
			self.defects(row("Seat Override Log", "Alumni", read=1, portal=1)),
			["Seat Override Log: Alumni can read a staff-only DocType"],
		)
		self.assertEqual(self.defects(row("Seat Override Log", "Registrar", read=1, portal=0)), [])
		self.assertEqual(
			self.defects(row("Seat Override Log", "Guest", read=1)),
			["Seat Override Log: Guest can read a staff-only DocType"],
		)

	def test_student_facing_write_create_delete_only_on_writable_doctypes(self):
		self.assertEqual(
			self.defects(row("Student Grievance", "Student", read=1, write=1, create=1, portal=1)), []
		)
		self.assertEqual(
			self.defects(row("Circular", "Student", read=1, write=1, create=1, delete=1, portal=1)),
			["Circular: Student can write", "Circular: Student can create", "Circular: Student can delete"],
		)
		self.assertEqual(
			self.defects(row("Student Grievance", "Student", read=1, delete=1, portal=1)),
			["Student Grievance: Student can delete"],
		)

	def test_reports_are_closed_to_student_facing_roles(self):
		self.assertEqual(
			self.defects(report_row("Result Summary", "Student", "Student Result", portal=1)),
			["Result Summary: Student can open a staff-only Report"],
		)
		self.assertEqual(self.defects(report_row("Result Summary", "COE", "Student Result", portal=0)), [])

	def test_report_on_confidential_doctype_has_listed_readers_only(self):
		self.assertEqual(self.defects(report_row("CO Report", "COE", "CO Attainment Snapshot")), [])
		self.assertEqual(
			self.defects(report_row("CO Report", "System Manager", "CO Attainment Snapshot")), []
		)
		self.assertEqual(
			self.defects(report_row("CO Report", "Academics User", "CO Attainment Snapshot")),
			["CO Report: Academics User can open a Report on a confidential DocType"],
		)

	def test_student_facing_roles_never_share_or_export(self):
		defects = self.defects(row("Student Result", "Student", read=1, share=1, export=1, portal=1))
		self.assertEqual(defects, ["Student Result: Student can share", "Student Result: Student can export"])
		self.assertEqual(self.defects(row("Student Result", "COE", read=1, share=1, export=1)), [])

	def test_confidential_doctype_has_listed_readers_only(self):
		self.assertEqual(self.defects(row("Counselling Note", "Mentor", read=1)), [])
		self.assertEqual(self.defects(row("Counselling Note", "System Manager", read=1)), [])
		self.assertEqual(
			self.defects(row("CO Attainment Snapshot", "HOD", read=1)),
			["CO Attainment Snapshot: HOD can read a confidential DocType"],
		)
		self.assertEqual(
			self.defects(row("Question Paper", "COE", write=1)), []
		)  # write without read is not a read

	def test_unlisted_confidential_doctypes_are_flagged(self):
		self.assertEqual(
			self.defects(restricted=["Secret Note"]), ["Secret Note: restricted record without a reader list"]
		)
		self.assertEqual(
			self.defects(row("New Exam Thing", "Exam Confidential", read=1)),
			["New Exam Thing: exam-confidential DocType without a reader list"],
		)


class TestPermissionMatrix(IntegrationTestCase):
	def test_site_has_no_permission_defects(self):
		rows = matrix.collect_rows()
		restricted = frappe.get_hooks("restricted_record_doctypes")
		self.assertEqual(matrix.find_defects(rows, restricted), [])

	def test_matrix_covers_doctypes_and_reports_and_writes_csv(self):
		rows = matrix.collect_rows()
		kinds = {r["kind"] for r in rows}
		self.assertEqual(kinds, {"DocType", "Report"})
		self.assertTrue(
			any(r["name"] == "Student Result" and r["role"] == "Student" and r["read"] for r in rows)
		)
		with tempfile.TemporaryDirectory() as folder:
			path = os.path.join(folder, "matrix.csv")
			matrix.write_csv(rows, path)
			with open(path) as out:
				written = list(csv.DictReader(out))
		self.assertEqual(len(written), len(rows))
		self.assertEqual(list(written[0])[:5], ["kind", "name", "ref_doctype", "role", "permlevel"])
		for column in ("if_owner", "report", "select", "amend", "import", "email", "submittable", "portal"):
			self.assertIn(column, written[0])

	def test_student_role_rows_are_tagged_portal(self):
		rows = matrix.collect_rows()
		self.assertTrue(all(r["portal"] for r in rows if r["role"] == "Student"))
		self.assertFalse(any(r["portal"] for r in rows if r["role"] == "System Manager"))

	def test_every_report_has_a_row_for_each_role_that_opens_it(self):
		rows = matrix.collect_rows()
		reports = {r["name"] for r in rows if r["kind"] == "Report"}
		modules = matrix.campus_modules()
		without_rows = set(frappe.get_all("Report", {"module": ["in", modules]}, pluck="name")) - reports
		for name in without_rows:  # only a Report on a DocType nobody can read may be absent
			self.assertFalse(
				frappe.db.get_value("Report", name, "ref_doctype")
				and frappe.get_meta(frappe.db.get_value("Report", name, "ref_doctype")).permissions,
				name,
			)

	def test_submittable_campus_doctypes_are_history_unless_exempt(self):
		rows = matrix.collect_rows()
		submittable = {r["name"] for r in rows if r["kind"] == "DocType" and r["submittable"]}
		self.assertIn("Question Paper", submittable)
		deletable = {
			r["name"]
			for r in rows
			if r["kind"] == "DocType" and r["submittable"] and r["delete"] and r["role"] != "System Manager"
		}
		self.assertEqual(deletable - set(matrix.HISTORY_EXEMPT), set())

	def test_every_history_doctype_exists(self):
		missing = [name for name in matrix.HISTORY_KEPT if not frappe.db.exists("DocType", name)]
		self.assertEqual(missing, [])  # a renamed DocType must not silently drop out of the rule

	def test_every_confidential_doctype_exists(self):
		missing = [name for name in matrix.CONFIDENTIAL_READERS if not frappe.db.exists("DocType", name)]
		self.assertEqual(missing, [])


class TestSiteCheck(IntegrationTestCase):
	def run_with(self, checks, profile):
		with patch.object(site_check, "CHECKS", checks):
			return site_check.run(profile)

	def test_production_profile_exits_non_zero_on_a_failing_item(self):
		checks = (("good", lambda: (site_check.OK, "fine")), ("bad", lambda: (site_check.FAIL, "broken")))
		with self.assertRaises(SystemExit) as raised:
			self.run_with(checks, "production")
		self.assertEqual(raised.exception.code, 1)

	def test_warnings_do_not_fail_production(self):
		checks = (("soft", lambda: (site_check.WARN, "meh")),)
		self.assertEqual(self.run_with(checks, "production"), [("soft", site_check.WARN, "meh")])

	def test_development_profile_reports_without_exiting(self):
		checks = (("bad", lambda: (site_check.FAIL, "broken")),)
		self.assertEqual(self.run_with(checks, "development"), [("bad", site_check.FAIL, "broken")])

	def test_developer_mode_and_allow_tests_are_judged_from_site_config(self):
		with patch.dict(frappe.local.conf, {"developer_mode": 0, "allow_tests": 0}):
			self.assertEqual(site_check.check_developer_mode()[0], site_check.OK)
			self.assertEqual(site_check.check_allow_tests()[0], site_check.OK)
		with patch.dict(frappe.local.conf, {"developer_mode": 1, "allow_tests": 1}):
			self.assertEqual(site_check.check_developer_mode()[0], site_check.FAIL)
			self.assertEqual(site_check.check_allow_tests()[0], site_check.FAIL)

	def test_every_item_runs_on_this_site(self):
		results = self.run_with(site_check.CHECKS, "development")
		self.assertEqual([r[0] for r in results], [name for name, _ in site_check.CHECKS])
		self.assertTrue(
			all(status in (site_check.OK, site_check.WARN, site_check.FAIL) for _, status, _ in results)
		)

	def test_error_log_and_mail_queue_counts(self):
		with patch.object(site_check, "ERROR_LOG_LIMIT", 10**9):
			self.assertEqual(site_check.check_error_log()[0], site_check.OK)
		with patch.object(site_check, "ERROR_LOG_LIMIT", -1):
			self.assertEqual(site_check.check_error_log()[0], site_check.FAIL)
		self.assertIn("outgoing mails in Error", site_check.check_mail_queue()[1])

	def test_whatsapp_unused_or_missing_is_a_warning_not_a_failure(self):
		with patch.object(frappe.db, "exists", return_value=False):
			self.assertEqual(site_check.check_whatsapp()[0], site_check.WARN)
		with patch.object(frappe.db, "get_single_value", return_value=None):
			self.assertEqual(site_check.check_whatsapp()[0], site_check.WARN)
		with (
			patch.object(frappe.db, "get_single_value", return_value="Main"),
			patch.object(frappe.db, "get_value", return_value="Active"),
		):
			self.assertEqual(site_check.check_whatsapp()[0], site_check.OK)

	def test_email_account_needs_a_default_outgoing_account(self):
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertEqual(site_check.check_email_account()[0], site_check.FAIL)
		with patch.object(frappe, "get_all", return_value=["Outgoing"]):
			self.assertEqual(
				site_check.check_email_account(), (site_check.OK, "default outgoing account: Outgoing")
			)

	def test_backups_report_each_missing_safeguard(self):
		settings = {"encrypt_backup": 0, "backup_limit": 0}
		with (
			patch.object(frappe, "get_system_settings", side_effect=settings.get),
			patch.dict(frappe.local.conf, {"encryption_key": ""}),
		):
			status, detail = site_check.check_backups()
		self.assertEqual(status, site_check.FAIL)
		for problem in ("not encrypted", "backup_limit is 0", "no encryption_key"):
			self.assertIn(problem, detail)
		settings = {"encrypt_backup": 1, "backup_limit": 3}
		with (
			patch.object(frappe, "get_system_settings", side_effect=settings.get),
			patch.dict(frappe.local.conf, {"encryption_key": "k"}),
		):
			self.assertEqual(site_check.check_backups()[0], site_check.OK)

	def test_scheduler_inactive_fails(self):
		with patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=True):
			self.assertEqual(site_check.check_scheduler()[0], site_check.FAIL)
		with patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=False):
			self.assertEqual(site_check.check_scheduler()[0], site_check.OK)

	def test_backup_age_warns_when_missing_or_old(self):
		with tempfile.TemporaryDirectory() as folder, patch.dict(frappe.local.conf, {"backup_path": folder}):
			with patch.object(frappe.utils, "get_site_path", return_value=folder):
				self.assertEqual(site_check.check_backup_age()[0], site_check.WARN)  # empty folder
				path = os.path.join(folder, "db.sql.gz")
				open(path, "w").close()
				self.assertEqual(site_check.check_backup_age()[0], site_check.OK)
				os.utime(path, (1, 1))
				self.assertEqual(site_check.check_backup_age()[0], site_check.WARN)

	def test_stuck_mail_is_a_warning(self):
		with patch.object(frappe.db, "count", return_value=3):
			self.assertEqual(site_check.check_mail_backlog()[0], site_check.WARN)
		with patch.object(frappe.db, "count", return_value=0):
			self.assertEqual(site_check.check_mail_backlog()[0], site_check.OK)
