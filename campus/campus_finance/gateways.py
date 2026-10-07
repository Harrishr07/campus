"""M09-06 Payment gateways: one Payment Gateway Account per company, a Pay-now link, and the gateway's payment webhook.

Reuses ERPNext's Payment Request and Payment Gateway Account (no gateway DocTypes here). The invoice's company picks
the Payment Gateway Account, so a trust (hostel) invoice is paid into the trust's account and a college invoice into the
college's. `fee_payment_link` (for the student portal) returns the Payment Request URL of the caller's own or ward's unpaid invoice.

A gateway is a `GatewayAdapter`: how to verify its webhook signature and read its event. Razorpay is implemented;
PayU and Cashfree register here in Phase 5. The webhook secret of each Payment Gateway Account is in the site config,
`campus_gateway_secrets` {account name: secret}, never in a DocType, and is never logged.

The webhook checks the signature and queues the settlement, which a background job runs as Administrator (ERPNext's
Payment Entry code needs a user's rights, a gateway has no session). The job settles the Payment Request under its row
lock; a repeated delivery finds the request Paid (or its Payment Entry) and does nothing, so one payment makes one
Payment Entry.
"""

import hashlib
import hmac
import json
from typing import NamedTuple

import frappe
from frappe import _
from frappe.utils import flt

from campus.examinations.api import students_of

OPEN_STATUSES = ("Requested", "Initiated")
JOB = "campus.campus_finance.gateways.settle_payment"


class PaymentEvent(NamedTuple):
	"""What a gateway reports: the Payment Request it was for, the gateway's payment id, and the amount captured."""

	payment_request: str
	gateway_payment_id: str
	amount: float


class GatewayAdapter:
	"""A gateway's webhook contract. Subclass, set `signature_header`, and add an instance to ADAPTERS."""

	signature_header = ""

	def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
		raise NotImplementedError

	def parse_event(self, payload: dict) -> PaymentEvent | None:
		"""The payment event in `payload`, or None when it is not a captured payment."""
		raise NotImplementedError


class RazorpayAdapter(GatewayAdapter):
	"""Razorpay: X-Razorpay-Signature is the hex HMAC-SHA256 of the raw body under the webhook secret; the Payment
	Request is named in the order notes (`payment_request`) and amounts are in paise."""

	signature_header = "X-Razorpay-Signature"

	def verify_signature(self, body, signature, secret):
		expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected, signature or "")

	def parse_event(self, payload):
		if payload.get("event") != "payment.captured":
			return None
		entity = (payload.get("payload") or {}).get("payment", {}).get("entity", {})
		request = (entity.get("notes") or {}).get("payment_request")
		if not request or not entity.get("id"):
			return None
		return PaymentEvent(request, entity["id"], flt(entity.get("amount")) / 100)


ADAPTERS = {"Razorpay": RazorpayAdapter()}


def adapter_for(payment_gateway):
	adapter = ADAPTERS.get(payment_gateway)
	if not adapter:
		frappe.throw(_("Payment gateway {0} is not supported yet.").format(payment_gateway))
	return adapter


# ---- Pay now ---------------------------------------------------------------------------------


def gateway_account(company):
	"""The company's default Payment Gateway Account (never another company's), with a supported gateway."""
	account = frappe.db.get_value(
		"Payment Gateway Account", {"company": company, "is_default": 1}, ["name", "payment_gateway", "payment_account", "payment_channel", "message"], as_dict=True
	)
	if not account:
		frappe.throw(_("{0} has no payment gateway set up.").format(company))
	adapter_for(account.payment_gateway)
	return account


def owns_invoice(user, invoice):
	"""Whether the invoice is the user's own or a ward's: its student is one of theirs, or it has none and is made out to their Customer."""
	mine = students_of(user)
	if invoice.student:
		return invoice.student in mine
	customers = frappe.get_all("Student", {"name": ["in", list(mine) or [""]]}, pluck="customer")
	return bool(invoice.customer and invoice.customer in customers)


def fee_payment_link(invoice):
	"""The gateway URL to pay the caller's own (or ward's) unpaid fee invoice, through the invoice company's gateway account.

	The same refusal for an invoice that does not exist or is not the caller's. Reuses the open Payment Request for the
	current outstanding amount; a stale one is cancelled first."""
	user = frappe.session.user
	found = frappe.db.get_value(
		"Sales Invoice", invoice, ["name", "company", "customer", "student", "docstatus", "is_return", "currency", "party_account_currency"], as_dict=True
	)
	if user == "Guest" or not found or found.docstatus != 1 or found.is_return or not owns_invoice(user, found):
		frappe.throw(_("You cannot pay this invoice."), frappe.PermissionError)
	outstanding = flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount", for_update=True), 2)  # serialise the requests
	if outstanding <= 0:
		frappe.throw(_("Nothing is due on {0}.").format(invoice))
	account = gateway_account(found.company)
	request = open_request(invoice, account.name, outstanding) or new_request(found, account, outstanding, user)
	if not request.payment_url:
		frappe.throw(_("The payment gateway is not available. Try again later."))
	return request.payment_url


def open_request(invoice, account, outstanding):
	"""The invoice's open Payment Request if it is for `outstanding` through `account`; any other open one is cancelled."""
	chosen = None
	for name in frappe.get_all(
		"Payment Request", {"reference_doctype": "Sales Invoice", "reference_name": invoice, "docstatus": 1, "status": ["in", OPEN_STATUSES]}, pluck="name"
	):
		request = frappe.get_doc("Payment Request", name, for_update=True)
		if not chosen and request.payment_gateway_account == account and flt(request.outstanding_amount, 2) == outstanding and request.payment_url:
			chosen = request
			continue
		request.flags.ignore_permissions = True
		request.cancel()
	return chosen


def new_request(invoice, account, outstanding, user):
	request = frappe.get_doc(
		{
			"doctype": "Payment Request", "payment_request_type": "Inward", "company": invoice.company,
			"payment_gateway_account": account.name, "payment_gateway": account.payment_gateway,
			"payment_account": account.payment_account, "payment_channel": account.payment_channel,
			"currency": invoice.currency, "grand_total": outstanding,
			"reference_doctype": "Sales Invoice", "reference_name": invoice.name, "party_type": "Customer", "party": invoice.customer,
			"party_account_currency": invoice.party_account_currency,
			"email_to": user, "subject": _("Payment Request for {0}").format(invoice.name),
			"message": account.message or _("Payment for {0}").format(invoice.name), "mute_email": 1,
		}
	)  # fmt: skip
	request.flags.ignore_permissions = True
	request.insert()
	return request.submit()


# ---- Webhook ---------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(gateway_account):
	"""The gateway's payment callback for one Payment Gateway Account. Signature first; nothing else is trusted."""
	body = frappe.request.get_data()
	account, adapter = verified_account(gateway_account, body)
	try:
		event = adapter.parse_event(json.loads(body))
	except ValueError:
		frappe.throw(_("Invalid payment notification."))
	if not event:
		return {"status": "ignored"}
	frappe.enqueue(JOB, queue="short", enqueue_after_commit=True, now=frappe.in_test, account=account, request=event.payment_request, amount=event.amount)
	return {"status": "accepted"}


def verified_account(gateway_account, body):
	"""(account name, adapter) when the request body is signed with the account's secret, else PermissionError.

	The secret lives only in this frame, which is gone before any work is done, so no later error report can carry it."""
	account = frappe.db.get_value("Payment Gateway Account", gateway_account, ["name", "payment_gateway"], as_dict=True)
	adapter = ADAPTERS.get(account and account.payment_gateway)
	secret = (frappe.conf.get("campus_gateway_secrets") or {}).get(gateway_account)
	signature = frappe.get_request_header(adapter.signature_header) if adapter else None
	if not (adapter and secret and signature and adapter.verify_signature(body, signature, secret)):
		frappe.throw(_("Invalid payment notification."), frappe.PermissionError)
	return account.name, adapter


def settle_payment(account, request, amount):
	"""Worker entry point: mark the Payment Request paid, once, as Administrator (a worker may; the web session is never touched).

	Needed because ERPNext's Payment Entry code checks the session user's rights on the invoice and accounts, and a gateway
	has no session. Returns {"status": "paid" | "duplicate" | "ignored"}."""
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		return settle(account, PaymentEvent(request, "", flt(amount)))
	finally:
		frappe.set_user(caller)


def settle(account, event):
	"""Mark the event's Payment Request paid, once. Under the request's row lock a repeated delivery sees it Paid."""
	found = frappe.db.get_value(
		"Payment Request", event.payment_request, ["payment_gateway_account", "docstatus", "status", "grand_total"], for_update=True, as_dict=True
	)  # the lock: a repeated delivery waits here and then sees Paid
	if not found or found.docstatus != 1 or found.payment_gateway_account != account:
		return {"status": "ignored"}
	if found.status == "Paid" or frappe.db.exists("Payment Entry", {"reference_no": event.payment_request, "docstatus": 1}):
		return {"status": "duplicate"}
	if abs(flt(found.grand_total) - event.amount) > 0.005:
		frappe.log_error(title="Payment amount mismatch", message=f"Payment Request {event.payment_request}: {event.amount} paid, {found.grand_total} asked.")
		frappe.throw(_("The amount paid does not match the payment request."))
	request = frappe.get_doc("Payment Request", event.payment_request)
	request.flags.ignore_permissions = True
	request.set_as_paid()
	return {"status": "paid"}
