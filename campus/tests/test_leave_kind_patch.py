"""M05-02 patch backfill_leave_kind: leaves made before `oc_leave_kind` existed become Medical, as the first rules counted them.

A unit test: the column check, the custom field setup and the UPDATE are mocked, so no DDL runs and nothing commits.
"""

from unittest.mock import patch

from frappe.tests import UnitTestCase

from campus.patches import backfill_leave_kind

MODULE = "campus.patches.backfill_leave_kind"


class TestLeaveKindPatch(UnitTestCase):
	def run_patch(self, column_existed):
		with (
			patch(f"{MODULE}.frappe.db.has_column", return_value=column_existed) as has_column,
			patch(f"{MODULE}.setup_student_services") as setup,
			patch(f"{MODULE}.frappe.db.sql") as sql,
		):
			backfill_leave_kind.execute()
		has_column.assert_called_once_with("Student Leave Application", "oc_leave_kind")
		setup.assert_called_once_with()
		sql.assert_called_once()
		return sql.call_args.args[0]

	def test_every_existing_leave_becomes_medical_when_the_column_is_new(self):
		query = self.run_patch(column_existed=False)
		self.assertEqual(query, "update `tabStudent Leave Application` set oc_leave_kind = 'Medical'")

	def test_a_rerun_fills_only_blank_rows(self):
		query = self.run_patch(column_existed=True)
		self.assertEqual(
			query,
			"update `tabStudent Leave Application` set oc_leave_kind = 'Medical' where oc_leave_kind is null or oc_leave_kind = ''",
		)
