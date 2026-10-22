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
		self.assertEqual(self.defects(row("Fine Rule", "Accounts Manager", delete=1)), [])  # not kept for history

	def test_student_facing_roles_read_only_listed_doctypes(self):
		self.assertEqual(self.defects(row("Student Result", "Student", read=1)), [])
		self.assertEqual(
			self.defects(row("Seat Override Log", "Guardian", read=1)),
			["Seat Override Log: Guardian can read a staff-only DocType"],
		)
		self.assertEqual(len(self.defects(row("Circular", "Guest", read=1, write=0))), 0)

	def test_student_facing_roles_never_share_or_export(self):
		defects = self.defects(row("Student Result", "Student", read=1, share=1, export=1))
		self.assertEqual(
			defects, ["Student Result: Student can share", "Student Result: Student can export"]
		)
		self.assertEqual(self.defects(row("Student Result", "COE", read=1, share=1, export=1)), [])

	def test_confidential_doctype_has_listed_readers_only(self):
		self.assertEqual(self.defects(row("Counselling Note", "Mentor", read=1)), [])
		self.assertEqual(self.defects(row("Counselling Note", "System Manager", read=1)), [])
		self.assertEqual(
			self.defects(row("CO Attainment Snapshot", "HOD", read=1)),
			["CO Attainment Snapshot: HOD can read a confidential DocType"],
		)
		self.assertEqual(self.defects(row("Question Paper", "COE", write=1)), [])  # write without read is not a read

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
		self.assertTrue(any(r["name"] == "Student Result" and r["role"] == "Student" and r["read"] for r in rows))
		with tempfile.TemporaryDirectory() as folder:
			path = os.path.join(folder, "matrix.csv")
			matrix.write_csv(rows, path)
			with open(path) as out:
				written = list(csv.DictReader(out))
		self.assertEqual(len(written), len(rows))
		self.assertEqual(list(written[0])[:4], ["kind", "name", "role", "permlevel"])

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
		self.assertTrue(all(status in (site_check.OK, site_check.WARN, site_check.FAIL) for _, status, _ in results))

	def test_error_log_and_mail_queue_counts(self):
		with patch.object(site_check, "ERROR_LOG_LIMIT", 10**9):
			self.assertEqual(site_check.check_error_log()[0], site_check.OK)
		with patch.object(site_check, "ERROR_LOG_LIMIT", -1):
			self.assertEqual(site_check.check_error_log()[0], site_check.FAIL)
		self.assertIn("Error", site_check.check_mail_queue()[1])
