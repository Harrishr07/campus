"""M16-03 Who can see a circular, the portal feed and acknowledgements.

A circular is visible to its audience only while it is approved (docstatus 1) and now is inside its publish
window. Staff roles (System Manager, Academics User) see circulars through the ordinary role permissions;
every other user, such as a student, guardian or employee on the portal, sees exactly the live circulars
whose audience includes them. Visibility is a pure function of the clock and the audience, so nothing
needs to be switched on or off when a window opens or closes.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.campus_messaging import audience

STAFF_ROLES = ("System Manager", "Academics User")
READ_TYPES = ("read", "print", "email", "export", "report", "select")


def live_circulars(at=None):
	"""[{name, audience_rule, ...}] of approved circulars whose publish window is open."""
	at = at or now_datetime()
	return frappe.get_all(
		"Circular",
		filters={"docstatus": 1, "publish_from": ["<=", at]},
		or_filters=[["publish_until", "is", "not set"], ["publish_until", ">", at]],
		fields=[
			"name",
			"title",
			"body",
			"company",
			"publish_from",
			"publish_until",
			"acknowledgement_required",
			"audience_rule",
		],
		order_by="publish_from desc",
	)


def circulars_for(user):
	"""Live circulars addressed to `user`, each with the recipient key that matched."""
	keys, members, result = audience.keys_for_user(user), {}, []
	for circular in live_circulars():
		if circular.audience_rule not in members:
			members[circular.audience_rule] = set(audience.resolve(circular.audience_rule))
		matched = sorted(keys & members[circular.audience_rule])
		if matched:
			result.append({**circular, "matched": matched[0]})
	return result


def is_staff(user):
	return user == "Administrator" or bool(set(STAFF_ROLES) & set(frappe.get_roles(user)))


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if is_staff(user):
		return ""
	names = [c["name"] for c in circulars_for(user)]
	if not names:
		return "1=0"
	return "`tabCircular`.name in ({})".format(", ".join(frappe.db.escape(n) for n in names))


def has_permission(doc, ptype=None, user=None):
	"""Non-staff users may only read circulars addressed to them that are live; staff are left to role permissions.

	A controller hook can only deny (a falsy result denies), so staff get True here, not None."""
	user = user or frappe.session.user
	if is_staff(user):
		return True
	if ptype and ptype not in READ_TYPES:
		return False
	return any(c["name"] == doc.name for c in circulars_for(user))


@frappe.whitelist()
def get_my_circulars():
	"""The portal feed: live circulars for the session user, newest first, with acknowledgement state."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Log in to see circulars."), frappe.PermissionError)
	circulars = circulars_for(user)
	acknowledged = set(
		frappe.get_all(
			"Circular Acknowledgement",
			filters={"user": user, "circular": ["in", [c["name"] for c in circulars] or [""]]},
			pluck="circular",
		)
	)
	return [
		{
			"name": c["name"],
			"title": c["title"],
			"body": c["body"],
			"publish_from": c["publish_from"],
			"publish_until": c["publish_until"],
			"acknowledgement_required": c["acknowledgement_required"],
			"acknowledged": c["name"] in acknowledged,
			"attachments": frappe.get_all(
				"File",
				filters={"attached_to_doctype": "Circular", "attached_to_name": c["name"]},
				fields=["file_name", "file_url", "is_private"],
			),
		}
		for c in circulars
	]


@frappe.whitelist()
def acknowledge(circular):
	"""Record that the session user has read a circular addressed to them; repeating it is harmless."""
	user = frappe.session.user
	match = next((c for c in circulars_for(user) if c["name"] == circular), None) if user != "Guest" else None
	if not match:
		frappe.throw(_("Circular {0} is not available to you.").format(circular), frappe.PermissionError)
	if not match["acknowledgement_required"]:
		frappe.throw(_("Circular {0} does not need acknowledgement.").format(circular))
	name = f"{circular}-{user}"
	if frappe.db.exists("Circular Acknowledgement", name):
		return name
	party_type, _sep, party = match["matched"].partition(":")
	acknowledgement = frappe.get_doc(
		{
			"doctype": "Circular Acknowledgement",
			"circular": circular,
			"user": user,
			"party_type": party_type,
			"party": party,
			"company": match["company"],
			"acknowledged_on": now_datetime(),
		}
	)
	try:
		acknowledgement.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:  # a concurrent request acknowledged first
		pass
	return name
