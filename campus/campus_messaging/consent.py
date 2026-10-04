"""M16-02 Consent decision.

Decision table (explicit record always wins):
  record Opted Out            -> not allowed
  record Opted In             -> allowed
  no record, transactional    -> allowed
  no record, promotional      -> NOT allowed (opt-in required)
Recipients without a party (bare phone numbers) have no records, so only the defaults apply.
"""

import frappe

OPTED_IN = "Opted In"
OPTED_OUT = "Opted Out"


def decide(status, purpose):
	"""Pure decision from the stored status (or None when there is no record)."""
	if status == OPTED_OUT:
		return False
	if status == OPTED_IN:
		return True
	return purpose == "transactional"


def is_allowed(party_type, party, channel, purpose):
	status = None
	if party_type and party:
		status = frappe.db.get_value(
			"Communication Consent",
			{"party_type": party_type, "party": party, "channel": channel, "purpose": purpose},
			"status",
		)
	return decide(status, purpose)
