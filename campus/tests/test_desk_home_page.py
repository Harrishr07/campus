"""A site whose setup was completed outside the wizard keeps desk's home page on the wizard; that loops /desk and /setup-wizard."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from campus.install import repair_desk_home_page


class TestDeskHomePage(IntegrationTestCase):
	def test_completed_setup_moves_desk_home_off_the_wizard(self):
		frappe.db.set_default("desktop:home_page", "setup-wizard")
		repair_desk_home_page()
		self.assertEqual(frappe.db.get_default("desktop:home_page"), "workspace")

	def test_pending_setup_keeps_the_wizard(self):
		frappe.db.set_default("desktop:home_page", "setup-wizard")
		with patch("frappe.is_setup_complete", return_value=False):
			repair_desk_home_page()
		self.assertEqual(frappe.db.get_default("desktop:home_page"), "setup-wizard")
