import frappe
from campus.student_services.setup import setup_student_guardian_fetch


def execute():
	"""BUG-07: Ensure Student Guardian child table has fetch_from configured so guardian_name and contact details
	are auto-populated from the linked Guardian record."""
	setup_student_guardian_fetch()
