"""Shared test base for OneBook Campus (P1-T01)."""

import frappe
from frappe.tests import IntegrationTestCase


class CampusTestCase(IntegrationTestCase):
	"""Base class for campus integration tests.

	Subclasses that need demo data override `load_demo_data`; it runs once per class.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.load_demo_data()

	@classmethod
	def load_demo_data(cls):
		"""Hook for loading demo data. No-op until the demo-data loader exists."""
