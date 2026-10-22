"""M04-07 Duplicate candidate detection: one rule for manual entry, uploads (M04-06) and the API.

A new Student Applicant, or one whose identity changes, is a possible duplicate of a record of the same college when
- its normalised name and date of birth equal an applicant's or a Student's (a returning student), or
- its qualifying-exam register number equals an applicant's and the exams agree (or one exam is blank).
A shared phone number or e-mail alone never makes a duplicate. The rule runs in the Student Applicant validate hook,
so desk entry, Data Import, the REST API and the bulk upload all refuse the duplicate with the same message.

Names compare as their letters only, case-folded and in any word order ("R. Asha Kumar" = "Kumar Asha R");
identifiers keep letters and digits, upper-cased. The register number is stored in that form.

Review: an upload row held as a possible duplicate becomes a Candidate Duplicate Review. An Admission Officer links it
to the existing record (no applicant is created) or marks it Not Duplicate with a reason (the applicant is created,
and only the matches the review recorded are cleared for it). Who decided, when and why stay on the review, which no
role can write: `decide` is the only way to change it, and it clears the candidate's raw values once decided.

Concurrency (MariaDB REPEATABLE READ): the matches are read with locking reads over the (company, date of birth) and
register-number index ranges, so a concurrent insert of the same candidate waits for this transaction's commit and
then sees its row. `oc_candidate_key` (exam + register no + date of birth + program + year, unique) backs the upload
retry. An upload preview reads without locks (it writes nothing).

Not yet (ledger): a desk "Open duplicate review" action for manual entry, needed before self-service or API intake;
`describe` names the matching records, which is fine for staff but must not reach a public caller.
"""

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import cstr, getdate, now_datetime

from campus.admissions.setup import OFFICER_ROLE

REVIEW = "Candidate Duplicate Review"
DECIDERS = (OFFICER_ROLE, "System Manager")
DECISIONS = ("Link", "Not Duplicate")
IDENTITY = ("first_name", "middle_name", "last_name", "date_of_birth", "oc_company", "oc_qualifying_exam", "oc_qualifying_register_no")
NAME_BASIS, EXAM_BASIS = "name and date of birth", "qualifying exam register number"


class DuplicateCandidateError(frappe.ValidationError):
	matches = ()


# ---- Student Applicant hook ---------------------------------------------------------------

def validate_applicant(doc, method=None):
	"""Normalise the register number, keep the candidate key and refuse a possible duplicate."""
	doc.oc_qualifying_register_no = id_key(doc.oc_qualifying_register_no) or None
	doc.oc_candidate_key = candidate_key(doc.oc_qualifying_register_no, doc.oc_qualifying_exam, doc.date_of_birth, doc.program, doc.academic_year)
	if not (doc.is_new() or any(doc.has_value_changed(f) for f in IDENTITY)):
		return
	cleared = cleared_matches(doc)
	found = [m for m in find_matches(doc) if (m.doctype, m.name) not in cleared]
	if found:
		error = DuplicateCandidateError()
		error.matches = found
		frappe.throw(describe(found), error, title=_("Possible Duplicate"))


def find_matches(doc):
	"""[{doctype, name, basis}] of the college's applicants and students this candidate may duplicate.

	Locking reads, except for an upload preview (`doc.flags.advisory_duplicate_check`): the preview writes
	nothing, so it need not hold gap locks while the rest of the file is checked."""
	if not doc.oc_company:
		return []
	lock = not doc.flags.advisory_duplicate_check
	matches = {}
	for row in same_birth_date("Student Applicant", doc, lock):
		add(matches, "Student Applicant", row.name, NAME_BASIS)
	for row in same_register_no(doc, lock):
		add(matches, "Student Applicant", row.name, EXAM_BASIS)
	for row in same_birth_date("Student", doc, lock):
		if row.student_applicant != doc.name and row.student_applicant not in matches:
			add(matches, "Student", row.name, NAME_BASIS)
	return list(matches.values())


def candidate_key(register_no, exam, date_of_birth, program, academic_year):
	"""Stable key of one application: the same exam and register no, birth date, program and year are one applicant."""
	register_no = id_key(register_no)
	if not (register_no and date_of_birth and program and academic_year):
		return None
	text = f"{id_key(exam)}|{register_no}|{getdate(date_of_birth)}|{program}|{academic_year}"
	return hashlib.sha1(text.encode()).hexdigest()


def describe(matches):
	listed = "; ".join(_("{0} {1} (same {2})").format(_(m.doctype), m.name, _(m.basis)) for m in matches)
	return _("This candidate may already exist: {0}.").format(listed)


# ---- review -------------------------------------------------------------------------------

def hold_for_review(values, matches, upload=None, upload_row=None):
	"""Record a possible duplicate for a reviewer; returns the review's name."""
	applicant = next((m.name for m in matches if m.doctype == "Student Applicant"), None)
	student = next((m.name for m in matches if m.doctype == "Student"), None)
	return frappe.get_doc(
		{
			"doctype": REVIEW, "company": values.get("oc_company"), "status": "Open",
			"candidate_name": " ".join(filter(None, (values.get(f) for f in ("first_name", "middle_name", "last_name")))),
			"date_of_birth": values.get("date_of_birth"), "qualifying_exam": values.get("oc_qualifying_exam"),
			"qualifying_register_no": values.get("oc_qualifying_register_no"), "program": values.get("program"),
			"academic_year": values.get("academic_year"), "existing_applicant": applicant, "existing_student": student,
			"match_summary": describe(matches), "matches": frappe.as_json([dict(m) for m in matches]),
			"candidate_values": frappe.as_json(values), "applicant_upload": upload, "upload_row": upload_row,
		}
	).insert(ignore_permissions=True).name  # fmt: skip


@frappe.whitelist(methods=["POST"])
def decide(review: str, decision: str, note: str | None = None):
	"""Link the candidate to the existing record or mark it Not Duplicate (creates the applicant); returns the record."""
	frappe.only_for(DECIDERS)
	frappe.has_permission(REVIEW, "read", review, throw=True)  # no role writes a review; read keeps the company scope
	if decision not in DECISIONS:
		frappe.throw(_("Choose Link or Not Duplicate."))
	if frappe.db.get_value(REVIEW, review, "status", for_update=True) != "Open":
		frappe.throw(_("This review has already been decided."))
	if decision == "Not Duplicate" and not cstr(note).strip():
		frappe.throw(_("Give the reason the candidate is not a duplicate."))
	doc = frappe.get_doc(REVIEW, review)
	doc.update({"decided_by": frappe.session.user, "decided_on": now_datetime(), "note": note})
	if decision == "Link":
		doc.update({"status": "Linked", "linked_applicant": doc.existing_applicant, "linked_student": None if doc.existing_applicant else doc.existing_student})
	else:
		doc.update({"status": "Not Duplicate", "new_applicant": create_cleared_applicant(doc)})
	doc.candidate_values = None  # personal data is needed only until the decision
	doc.flags.from_decide = True
	doc.save(ignore_permissions=True, ignore_version=False)  # the decision is always versioned
	from campus.admissions import applicant_upload

	applicant_upload.review_decided(doc)
	return doc.new_applicant or doc.linked_applicant or doc.linked_student


def create_cleared_applicant(review):
	applicant = frappe.get_doc({"doctype": "Student Applicant", **json.loads(review.candidate_values), "oc_duplicate_review": review.name})
	applicant.flags.cleared_matches = recorded_matches(review.matches)
	applicant.insert(ignore_permissions=True)
	return applicant.name


def cleared_matches(doc):
	"""Matches a Not Duplicate review cleared for this applicant (only the review's own new applicant)."""
	if doc.flags.cleared_matches is not None:
		return doc.flags.cleared_matches
	if not doc.oc_duplicate_review:
		return set()
	review = frappe.db.get_value(REVIEW, doc.oc_duplicate_review, ["status", "new_applicant", "matches"], as_dict=True)
	if not review or review.status != "Not Duplicate" or review.new_applicant != doc.name:
		return set()
	return recorded_matches(review.matches)


def recorded_matches(matches):
	return {(m["doctype"], m["name"]) for m in json.loads(matches or "[]")}


# ---- lookups and keys ---------------------------------------------------------------------

def same_birth_date(doctype, doc, lock=True):
	"""The college's records born the same day whose name matches (a locking read unless `lock` is off)."""
	name = name_key(doc.first_name, doc.middle_name, doc.last_name)
	if not (doc.date_of_birth and name):
		return []
	table = frappe.qb.DocType(doctype)
	columns = [table.name, table.first_name, table.middle_name, table.last_name]
	if doctype == "Student":
		columns.append(table.student_applicant)
	condition = (table.oc_company == doc.oc_company) & (table.date_of_birth == getdate(doc.date_of_birth))
	if doctype == "Student Applicant":
		condition &= table.name != cstr(doc.name)
	query = frappe.qb.from_(table).select(*columns).where(condition).orderby(table.name)
	rows = (query.for_update() if lock else query).run(as_dict=True)
	return [r for r in rows if name_key(r.first_name, r.middle_name, r.last_name) == name]


def same_register_no(doc, lock=True):
	if not doc.oc_qualifying_register_no:
		return []
	table = frappe.qb.DocType("Student Applicant")
	query = (
		frappe.qb.from_(table)
		.select(table.name, table.oc_qualifying_exam)
		.where((table.oc_company == doc.oc_company) & (table.oc_qualifying_register_no == doc.oc_qualifying_register_no) & (table.name != cstr(doc.name)))
		.orderby(table.name)
	)
	rows = (query.for_update() if lock else query).run(as_dict=True)
	return [r for r in rows if same_exam(id_key(r.oc_qualifying_exam), id_key(doc.oc_qualifying_exam))]


def add(matches, doctype, name, basis):
	if name in matches:
		matches[name].basis = f"{matches[name].basis}, {basis}"
	else:
		matches[name] = frappe._dict(doctype=doctype, name=name, basis=basis)


def name_key(*parts):
	words = re.findall(r"[^\W\d_]+", " ".join(cstr(p) for p in parts).casefold())
	return " ".join(sorted(words))


def id_key(value):
	return re.sub(r"[^0-9A-Z]", "", cstr(value).upper())


def same_exam(one, other):
	return not one or not other or one == other
