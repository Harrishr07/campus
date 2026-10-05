"""M04 Admit and Cancellation do accounting work (invoice, credit note, payment entry) that an Admission
Officer has no Account/Payment Entry rights for. The officer's role and company were already checked by the
caller; the accounting step runs as Administrator for the span of this context only."""

from contextlib import contextmanager

import frappe


@contextmanager
def system_user():
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(user)
