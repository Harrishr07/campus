"""M05-02 patch backfill_leave_kind: leaves made before `oc_leave_kind` existed become Medical, as the first rules counted them."""

import frappe

from campus.patches import backfill_leave_kind
from campus.tests.utils import CampusTestCase

FIELD = "Student Leave Application-oc_leave_kind"


def make_leave():
	leave = frappe.get_doc({"doctype": "Student Leave Application", "from_date": "2022-06-06", "to_date": "2022-06-06"})
	leave.flags.ignore_validate = leave.flags.ignore_links = leave.flags.ignore_mandatory = True
	return leave.insert(ignore_permissions=True).name


def kind(name):
	return frappe.db.get_value("Student Leave Application", name, "oc_leave_kind")


class TestLeaveKindPatch(CampusTestCase):
	"""Dropping the field is DDL (it commits), so this class cleans up after itself."""

	def tearDown(self):
		frappe.db.delete("Student Leave Application", {"student": ["is", "not set"]})
		frappe.db.commit()

	def test_existing_leaves_become_medical_when_the_column_is_new(self):
		frappe.delete_doc("Custom Field", FIELD, force=True)
		if frappe.db.has_column("Student Leave Application", "oc_leave_kind"):
			frappe.db.sql_ddl("alter table `tabStudent Leave Application` drop column oc_leave_kind")
		frappe.db.commit()
		frappe.clear_cache(doctype="Student Leave Application")
		self.assertFalse(frappe.db.has_column("Student Leave Application", "oc_leave_kind"))
		name = make_leave()
		backfill_leave_kind.execute()
		self.assertTrue(frappe.db.has_column("Student Leave Application", "oc_leave_kind"))
		self.assertEqual(kind(name), "Medical")

	def test_rerun_only_fills_blank_rows(self):
		backfill_leave_kind.execute()
		kept, blank = make_leave(), make_leave()
		frappe.db.set_value("Student Leave Application", kept, "oc_leave_kind", "On Duty")
		frappe.db.set_value("Student Leave Application", blank, "oc_leave_kind", "")
		backfill_leave_kind.execute()
		self.assertEqual((kind(kept), kind(blank)), ("On Duty", "Medical"))
