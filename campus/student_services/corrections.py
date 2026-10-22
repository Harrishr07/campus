"""M05-11 Student record corrections (NFR history preservation): a change to a student's personal, contact,
guardian, identity-document or academic-identifier field is a Student Record Correction, never a direct edit.

The request keeps the old value and the new value with a reason and a private evidence file, runs through the
approval engine (seeded policies: the COE; identity and academic identifiers also the Principal) and is applied only
by `apply_correction`, the policy's final action, which saves the Student (or Guardian) and keeps a Version of the
change. Office roles raise any category; a student or guardian raises the portal categories from the portal. The
lifecycle status is not correctable here (campus.student_services.lifecycle). Fields listed in Student Correction
Settings are locked against direct edit of the Student (`guard_locked_fields`) except for the override role.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime
from frappe.utils.password import delete_all_passwords_for

from campus.admissions import aadhaar
from campus.campus_platform.api import find_policy, start_request
from campus.student_services import correction_rules as rules

DOCTYPE, SETTINGS = "Student Record Correction", "Student Correction Settings"
DRAFT, PENDING, APPROVED, REJECTED, APPLIED = "Draft", "Pending", "Approved", "Rejected", "Applied"
OPEN = (DRAFT, PENDING, APPROVED)
FINAL_ACTION = "campus.student_services.corrections.apply_correction"
POLICY, HIGHER_POLICY = "Student Record Correction", "Student Record Correction (identity and academic)"
# title, position, scope field, SLA hours
FIRST_LEVEL = ("COE review", "COE", "company", 72)
SECOND_LEVEL = ("Principal approval", "PRINCIPAL", "company", 72)


# ---- the request ----------------------------------------------------------------------------


def check_desk_access(doc):
	"""A desk correction is raised only by someone who reads the student (role, company User Permission and the
	Student's permission hooks); a portal one was resolved by raise_correction."""
	if not frappe.db.exists("Student", doc.student):
		frappe.throw(_("Student {0} does not exist.").format(frappe.bold(doc.student)))
	if not frappe.has_permission("Student", "read", doc=doc.student):
		frappe.throw(_("You are not permitted to act for {0}.").format(frappe.bold(doc.student)), frappe.PermissionError)


def prepare(doc):
	"""Validate a correction and fill what the server decides: company, current value, normalised new value."""
	student = frappe.db.get_value("Student", doc.student, ["student_name", "oc_company"], as_dict=True)
	if not student:
		frappe.throw(_("Student {0} does not exist.").format(frappe.bold(doc.student)))
	doc.company = student.oc_company
	doc.student_name = student.student_name
	check_field(doc)
	check_no_open_correction(doc)
	target = target_of(doc)
	doc.old_value = current_value(target, doc.field_name)
	store_new_value(doc, target)
	check_unchanged(doc, target)
	check_evidence_is_private(doc)


def check_field(doc):
	problem = rules.refusal(doc.category, doc.field_name, portal=doc.requested_via == "Portal")
	if problem == "category":
		frappe.throw(_("Choose the category of the correction."))
	if problem == "field":
		frappe.throw(
			_("{0} cannot be corrected as {1}. Allowed: {2}.").format(
				frappe.bold(doc.field_name), _(doc.category), ", ".join(rules.allowed_fields(doc.category))
			)
		)
	if problem == "portal":
		frappe.throw(_("{0} corrections are raised by the college office.").format(_(doc.category)))


def check_no_open_correction(doc):
	filters = {"student": doc.student, "field_name": doc.field_name, "status": ["in", OPEN], "name": ["!=", doc.name or ""]}
	if doc.category == rules.GUARDIAN:
		filters["guardian"] = doc.guardian
	if other := frappe.db.get_value(DOCTYPE, filters):
		frappe.throw(_("{0} already has an open correction of {1}: {2}.").format(frappe.bold(doc.student), frappe.bold(doc.field_name), other))


def target_of(doc):
	"""The Student, or for a guardian correction the Guardian of the student, the correction would change."""
	if doc.category != rules.GUARDIAN:
		return frappe.get_doc("Student", doc.student)
	if not doc.guardian:
		frappe.throw(_("Choose the guardian whose details are corrected."))
	if not frappe.db.exists("Student Guardian", {"parent": doc.student, "parenttype": "Student", "guardian": doc.guardian}):
		frappe.throw(_("{0} is not a guardian of {1}.").format(frappe.bold(doc.guardian), frappe.bold(doc.student)))
	return frappe.get_doc("Guardian", doc.guardian)


def current_value(target, fieldname):
	value = target.get("oc_aadhaar_masked") if fieldname == aadhaar.AADHAAR_FIELD else target.get(fieldname)
	return "" if value is None else str(value)


def store_new_value(doc, target):
	"""Normalise the typed value, and prove the record would accept it, so approval never fails at apply time."""
	value = (doc.new_value or "").strip()
	if not value:
		frappe.throw(_("Enter the correct value."))
	if doc.field_name == aadhaar.AADHAAR_FIELD:
		store_aadhaar(doc, value)
		return
	doc.new_secret = None
	if target.meta.get_field(doc.field_name).fieldtype == "Date":
		value = str(getdate(value))
	doc.new_value = value
	probe = frappe.get_doc(target.doctype, target.name)
	probe.set(doc.field_name, value)
	probe._action = "save"
	probe._validate_data_fields()
	probe._validate_selects()
	probe._validate_links()
	if doc.category == rules.ACADEMIC and frappe.db.exists("Student", {doc.field_name: value, "name": ["!=", doc.student]}):
		frappe.throw(_("{0} {1} already belongs to another student.").format(frappe.bold(doc.field_name), frappe.bold(value)))


def store_aadhaar(doc, value):
	"""The number is kept encrypted in a Password field; the correction shows it masked. A masked value is accepted
	only as the unchanged value of a saved correction, whose stored secret is checked again."""
	if value.startswith(rules.MASK_PREFIX):
		before = None if doc.is_new() else doc.get_doc_before_save()
		unchanged = before and before.new_value == value and doc.new_secret and doc.is_dummy_password(doc.new_secret)
		if not (unchanged and aadhaar.is_valid_aadhaar(doc.get_password("new_secret", raise_exception=False) or "")):
			frappe.throw(_("Enter the full Aadhaar number."))
		return
	if not aadhaar.is_valid_aadhaar(value):
		frappe.throw(_("Aadhaar number is not valid. Enter 12 digits, not starting with 0 or 1."))
	doc.new_secret = aadhaar.normalize(value)
	doc.new_value = aadhaar.mask(value)


def check_unchanged(doc, target):
	if doc.field_name != aadhaar.AADHAAR_FIELD and str(doc.new_value) == doc.old_value:
		frappe.throw(_("{0} is already {1}; there is nothing to correct.").format(frappe.bold(doc.field_name), frappe.bold(doc.new_value)))


def check_evidence_is_private(doc):
	if doc.evidence and not doc.evidence.startswith("/private/"):
		frappe.throw(_("Attach the evidence as a private file."))


def before_request(doc):
	"""Approval request hook: a correction needs its evidence (except contact details) and a policy; a rejected one
	is the record of the refusal and is never sent again."""
	if doc.status == REJECTED:
		frappe.throw(_("{0} was rejected; raise a new correction.").format(doc.name))
	if rules.needs_evidence(doc.category) and not doc.evidence:
		frappe.throw(_("Attach the evidence for a {0} correction.").format(_(doc.category)))
	if not find_policy(doc):
		frappe.throw(_("No Approval Policy is set for {0}; it cannot be applied without approval.").format(_(DOCTYPE)))
	doc.db_set("old_value", current_value(target_of(doc), doc.field_name), update_modified=False)  # what the approvers are shown


# ---- status and apply -----------------------------------------------------------------------


def sync_status(request, method=None):
	"""Approval Request hook: the correction shows the request's state (the final action sets Applied)."""
	if request.reference_doctype != DOCTYPE or not frappe.db.exists(DOCTYPE, request.reference_name):
		return
	status = {"Pending": PENDING, "Returned": DRAFT, "Rejected": REJECTED, "Approved": APPROVED}.get(request.status)
	if not status:
		return
	frappe.db.set_value(DOCTYPE, request.reference_name, "status", status, update_modified=False)
	if status == REJECTED:
		delete_all_passwords_for(DOCTYPE, request.reference_name)


def apply_correction(doc, request=None):
	"""Final action of the approval policy: change the Student (or Guardian), keep a Version, mark Applied."""
	if frappe.db.get_value(DOCTYPE, doc.name, "status", for_update=True) == APPLIED:
		return
	target_doctype, target_name = ("Guardian", doc.guardian) if doc.category == rules.GUARDIAN else ("Student", doc.student)
	frappe.db.get_value(target_doctype, target_name, "name", for_update=True)  # one change at a time
	before = frappe.get_doc(target_doctype, target_name)
	if current_value(before, doc.field_name) != (doc.old_value or ""):
		frappe.throw(_("{0} has changed since the correction was requested; raise a new correction.").format(frappe.bold(doc.field_name)))
	failed = False
	try:
		save_target(doc, target_doctype, target_name)
	except Exception:
		failed = True  # raised outside the handler: no frame holding the decrypted value reaches a traceback or log
	if failed:
		frappe.throw(_("The correction could not be applied."))
	version = keep_version(before, frappe.get_doc(target_doctype, target_name))
	doc.db_set(
		{"status": APPLIED, "applied_on": now_datetime(), "applied_by": frappe.session.user, "version": version},
		update_modified=False,
	)
	delete_all_passwords_for(DOCTYPE, doc.name)


def save_target(doc, target_doctype, target_name):
	target = frappe.get_doc(target_doctype, target_name)
	target.set(doc.field_name, doc.get_password("new_secret") if doc.field_name == aadhaar.AADHAAR_FIELD else doc.new_value)
	target.flags.from_correction = True
	target.flags.ignore_permissions = True
	target.save()


def keep_version(before, target):
	"""The Version holding the change; made here when the DocType does not track changes itself."""
	after = frappe.get_doc(target.doctype, target.name)  # reloaded: a secret shows as asterisks in the diff
	if after.meta.track_changes:
		return frappe.db.get_value("Version", {"ref_doctype": after.doctype, "docname": after.name}, "name", order_by="creation desc")
	version = frappe.new_doc("Version")
	if version.update_version_info(before, after):
		return version.insert(ignore_permissions=True).name


# ---- lock against direct edit ---------------------------------------------------------------


def settings():
	return frappe.get_cached_doc(SETTINGS)  # a Single carries its field defaults only when loaded as a document


def locked_fields():
	return rules.locked_fields(settings().get("locked_fields"), rules.student_fields())


def guard_locked_fields(doc, method=None):
	"""Student validate: a locked field changes only through a correction (or for the override role)."""
	if doc.is_new() or doc.flags.from_correction:
		return
	changed = [name for name in locked_fields() if doc.has_value_changed(name)]
	if not changed or (settings().get("override_role") or "System Manager") in frappe.get_roles():
		return
	frappe.throw(
		_("{0} cannot be edited directly; raise a Student Record Correction.").format(", ".join(frappe.bold(n) for n in changed)),
		frappe.PermissionError,
	)


# ---- seeds ----------------------------------------------------------------------------------


def seed_policies():
	"""A COE approval for every correction, and COE then Principal for identity and academic identifiers, unless
	the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": DOCTYPE}):
		return
	if not (frappe.db.exists("Position", FIRST_LEVEL[1]) and frappe.db.exists("Position", SECOND_LEVEL[1])):
		return
	higher = f'doc.category in {tuple(rules.HIGHER_CATEGORIES)!r}'
	for name, levels, priority, condition in ((POLICY, [FIRST_LEVEL], 0, None), (HIGHER_POLICY, [FIRST_LEVEL, SECOND_LEVEL], 10, higher)):
		frappe.get_doc(
			{
				"doctype": "Approval Policy", "policy_name": name, "document_type": DOCTYPE, "priority": priority,
				"condition": condition, "on_final_action": "Call Service", "final_method": FINAL_ACTION,
				"levels": [
					{"title": title, "approver_type": "Position", "approver": position, "scope_field": scope, "sla_hours": hours}
					for title, position, scope, hours in levels
				],
			}
		).insert(ignore_permissions=True)  # fmt: skip


# ---- portal ---------------------------------------------------------------------------------


def correctable_fields(student):
	"""[{category, fields: [{fieldname, label}]}] a student or guardian may raise (the same for every student)."""
	rows = []
	for category in rules.PORTAL_CATEGORIES:
		doctype = rules.target_doctype(category)
		meta = frappe.get_meta(doctype)
		rows.append(
			{
				"category": category,
				"fields": [{"fieldname": f, "label": _(meta.get_label(f))} for f in rules.allowed_fields(category)],
			}
		)
	return rows


def student_guardians(student):
	rows = frappe.get_all("Student Guardian", {"parent": student, "parenttype": "Student"}, ["guardian", "guardian_name"], order_by="idx")
	return [{"name": row.guardian, "guardian_name": row.guardian_name or row.guardian} for row in rows]


@frappe.whitelist(methods=["POST"])
def raise_correction(category, field_name, new_value, reason, student=None, guardian=None):
	"""A student (or their guardian) asks for a correction; returns its row. The student comes from the portal's
	resolve_student, the category and field from the portal list, and the evidence file posted with the request is
	attached privately before approval is requested."""
	from campus.student_services import portal

	student = portal.resolve_student(student)
	upload = portal.uploaded_file()
	if rules.needs_evidence(category) and not upload:
		frappe.throw(_("Attach the evidence for a {0} correction.").format(_(category)))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE, "student": student, "category": category, "field_name": field_name,
			"guardian": guardian or None, "new_value": new_value, "reason": (reason or "").strip(),
		}
	)  # fmt: skip
	doc.flags.from_portal = True  # sets requested_via; only this server path sets the flag (flags never come from a client)
	doc.flags.ignore_permissions = True  # portal roles hold no right on the DocType; the checks above and in validate stand
	doc.insert()
	if upload:
		portal.attach_private(doc, "evidence", *upload)
		doc.reload()
	start_request(doc)
	doc.reload()
	return correction_row(doc)


@frappe.whitelist()
def my_corrections(student=None):
	from campus.student_services import portal

	student = portal.resolve_student(student)
	names = frappe.get_all(DOCTYPE, {"student": student}, pluck="name", order_by="creation desc")
	return {"student": student, "corrections": [correction_row(frappe.get_doc(DOCTYPE, n)) for n in names]}


def correction_row(doc):
	return {
		"name": doc.name, "category": doc.category, "field_name": doc.field_name, "old_value": doc.old_value,
		"new_value": doc.new_value, "status": doc.status, "reason": doc.reason, "applied_on": doc.applied_on,
	}  # fmt: skip
