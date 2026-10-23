"""M17-01 migrate imports a campus module added to modules.txt on the first run (refresh_module_map)."""

import copy
from unittest import mock

import frappe

from campus.campus_platform.module_map import refresh_module_map
from campus.install import before_migrate
from campus.tests.utils import CampusTestCase


class TestModuleMap(CampusTestCase):
	def setUp(self):
		self.addCleanup(setattr, frappe.local, "app_modules", copy.deepcopy(frappe.local.app_modules))

	def test_stale_map_gains_the_new_module(self):
		"""The map as Frappe holds it during the first migrate after Campus Approvals was added to modules.txt."""
		stale = copy.deepcopy(frappe.local.app_modules)
		stale["campus"].remove("campus_approvals")
		frappe.local.app_modules = stale
		frappe.cache.set_value("app_modules", stale)
		self.addCleanup(frappe.cache.delete_value, "app_modules")  # the next init rebuilds it from modules.txt

		refresh_module_map()

		self.assertIn("campus_approvals", frappe.local.app_modules["campus"])
		self.assertEqual(frappe.local.module_app["campus_approvals"], "campus")
		self.assertIn("campus_approvals", frappe.cache.get_value("app_modules")["campus"])

	def test_current_map_is_left_alone(self):
		with mock.patch.object(frappe, "setup_module_map") as rebuild:
			refresh_module_map()
		rebuild.assert_not_called()

	def test_before_migrate_refreshes_the_map_first(self):
		calls = []
		with (
			mock.patch("campus.install.refresh_module_map", side_effect=lambda: calls.append("map")),
			mock.patch("campus.install.ensure_coe_role", side_effect=lambda: calls.append("roles")),
		):
			before_migrate()
		self.assertEqual(calls[:2], ["map", "roles"])
