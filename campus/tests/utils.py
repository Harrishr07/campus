"""Shared test base for OneBook Campus (P1-T01)."""

import frappe
from frappe.tests import IntegrationTestCase


class CampusTestCase(IntegrationTestCase):
	"""Base class for campus integration tests.

	Subclasses that need demo data set `demo_scale` ("small" or "full") or override
	`load_demo_data`; it runs once per class.
	"""

	demo_scale = None

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.load_demo_data()

	@classmethod
	def load_demo_data(cls):
		"""Hook for loading demo data: the standard set at `demo_scale`, nothing when unset."""
		if cls.demo_scale:
			from campus.tests.demo import make_demo

			make_demo(cls.demo_scale)
