"""M04-06 Applicant Upload: staff bulk upload of Student Applicants with a validation preview and row outcomes.

Flow: an Applicant Upload (company, academic year, CSV/XLSX in the approved template) is validated with
`validate_upload`: every file row becomes an Applicant Upload Row with its preview status, and no applicant is
written. `start_import` then queues the Valid and Possible Duplicate rows on the bulk runner (chunk=1); each row
is inserted as an ordinary Student Applicant, so the same server rules as manual entry and the API apply again at
commit (mandatory and link checks, company scope, the M04-07 duplicate rule). File parsing, private storage and
value coercion are shared with the allotment import.

Preview statuses: Valid; Invalid (a required template cell is blank, a value is malformed, a rule refuses it, or the
row repeats an earlier row's candidate key); Possible Duplicate (the M04-07 rule, or an earlier row with the same
name and birth date or register number); Already Imported (an applicant with the row's candidate key exists).
The preview runs the Student Applicant validation in memory inside a savepoint that is always rolled back.

Outcomes: Created, Unchanged (already imported), Held for Review (a Candidate Duplicate Review was opened), Error,
and after a review Linked or Created. The upload is Awaiting Review while a review is open.

Idempotency: the candidate key (register no + date of birth + program + year, unique on Student Applicant) is read
with a locking read before the insert, so uploading the same file again, or two uploads at once, never creates a
second applicant. An upload is imported once; a retry is a new upload, whose preview shows the rows already imported.
A run that ends with rows still waiting (a lost transaction) is finished by `reconcile` (hourly): those rows become
Error rows asking for a new upload, so an upload never stays Importing.

Personal data: rows carry the upload's company (User Permissions scope them); once nothing is left to import, the
rows' raw file values and the uploaded file are deleted, keeping the file's sha256.
"""

import csv
import hashlib
import io
import json

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cstr

from campus.admissions import allotment_import, duplicates
from campus.campus_platform.bulk import run_bulk

UPLOAD, ROW = "Applicant Upload", "Applicant Upload Row"
HANDLER = "campus.admissions.applicant_upload.process_row"
KEY = "campus.admissions.applicant_upload.row_key"
SAVEPOINT, DRY_RUN = "applicant_upload_row", "applicant_upload_preview"
COLUMNS = {
	"First Name": "first_name", "Middle Name": "middle_name", "Last Name": "last_name", "Date of Birth": "date_of_birth",
	"Gender": "gender", "Email": "student_email_id", "Mobile": "student_mobile_number", "Program": "program",
	"Student Category": "student_category", "Admission Quota": "oc_admission_quota", "Admission Type": "oc_admission_type",
	"Qualifying Exam": "oc_qualifying_exam", "Qualifying Register No": "oc_qualifying_register_no",
}  # fmt: skip
REQUIRED = ("First Name", "Date of Birth", "Program", "Qualifying Exam", "Qualifying Register No")
QUEUED = ("Valid", "Possible Duplicate")
DONE = ("Created", "Unchanged", "Linked", "Already Imported")


@frappe.whitelist()
def download_template():
	"""The approved upload template: a CSV with the header row only."""
	out = io.StringIO()
	csv.writer(out).writerow(COLUMNS)
	frappe.response.update({"type": "csv", "doctype": "Applicant Upload Template", "result": out.getvalue()})


@frappe.whitelist(methods=["POST"])
def validate_upload(name: str):
	"""Preview the file: one Applicant Upload Row per file row with its status; returns {status: count}."""
	frappe.has_permission(UPLOAD, "write", name, throw=True)
	frappe.has_permission("Student Applicant", "create", throw=True)
	if frappe.db.get_value(UPLOAD, name, "status", for_update=True) not in ("Draft", "Validated"):
		frappe.throw(_("This upload has already been imported."))
	upload = frappe.get_doc(UPLOAD, name)
	content = allotment_import.read_file(upload.upload_file)
	content = content.encode() if isinstance(content, str) else content
	url = allotment_import.make_private(upload.upload_file, UPLOAD, "upload_file") or upload.upload_file
	rows = file_rows(allotment_import.parse_file(url, content))
	frappe.db.delete(ROW, {"applicant_upload": name})
	check = RowCheck(upload)
	for row_no, values in rows:
		save_row(upload, row_no, values, *check.preview(row_no, values))
	upload.db_set({"status": "Validated", "total_rows": len(rows), "file_sha256": hashlib.sha256(content).hexdigest()})
	return refresh_summary(name)


@frappe.whitelist(methods=["POST"])
def start_import(name: str):
	"""Queue the Valid and Possible Duplicate rows of a validated upload; returns the Bulk Run name (None if none)."""
	frappe.has_permission(UPLOAD, "write", name, throw=True)
	frappe.has_permission("Student Applicant", "create", throw=True)
	if frappe.db.get_value(UPLOAD, name, "status", for_update=True) != "Validated":
		frappe.throw(_("Validate the upload first; an upload is imported once."))
	rows = frappe.get_all(ROW, {"applicant_upload": name, "status": ["in", QUEUED]}, ["name", "row_no"], order_by="row_no")
	frappe.db.set_value(UPLOAD, name, "status", "Importing")
	if not rows:
		refresh_status(name)
		return None
	items = [{"upload": name, "row": r.name, "row_no": r.row_no} for r in rows]
	run = run_bulk("Applicant Upload", items, HANDLER, chunk=1, key=KEY, parameters={"upload": name})
	frappe.db.set_value(UPLOAD, name, "bulk_run", run)
	return run


def row_key(item):
	return f"{item['upload']}::{item['row_no']}"


# ---- import -------------------------------------------------------------------------------

def process_row(item, run):
	"""Bulk handler: create the applicant of one row, or hold it for review; DB-only, no commit."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		outcome = import_row(item)
	except frappe.QueryDeadlockError:
		raise  # every savepoint is gone: the runner rolls back and records the item as failed
	except Exception as e:  # noqa: BLE001 - a failing row is recorded, never stalls the upload
		frappe.db.rollback(save_point=SAVEPOINT)
		outcome = ("Error", None, None, cstr(e))
	set_outcome(item["row"], *outcome)
	refresh_status(item["upload"])


def import_row(item):
	"""(status, applicant, review, message) of one row."""
	upload = frappe.db.get_value(UPLOAD, item["upload"], ["name", "company", "academic_year"], as_dict=True)
	fields = applicant_fields(upload, json.loads(frappe.db.get_value(ROW, item["row"], "values_json")))
	existing = imported_applicant(fields)
	if existing:
		return "Unchanged", existing, None, _("Already imported.")
	doc = frappe.get_doc({"doctype": "Student Applicant", **fields})
	try:
		doc.insert(ignore_permissions=True)
	except duplicates.DuplicateCandidateError as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		review = duplicates.hold_for_review(fields, error.matches, upload.name, item["row"])
		return "Held for Review", None, review, cstr(error)
	except frappe.UniqueValidationError as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		existing = imported_applicant(fields)  # another upload committed the same candidate meanwhile
		if existing:
			return "Unchanged", existing, None, _("Already imported.")
		if "student_email_id" in cstr(error):
			return "Error", None, None, _("Another applicant already has this e-mail address.")
		return "Error", None, None, _("A value of this row must be unique and is already used.")
	return "Created", doc.name, None, ""


def imported_applicant(fields):
	"""Locking read: the applicant already holding this row's candidate key (latest committed), or None."""
	return frappe.db.get_value("Student Applicant", {"oc_candidate_key": key_of(fields)}, "name", for_update=True)


def review_decided(review):
	"""A reviewer decided a held row: record its outcome and complete the upload when nothing is left."""
	if not review.upload_row:
		return
	if review.status == "Linked":
		target = review.linked_applicant or review.linked_student
		set_outcome(review.upload_row, "Linked", review.linked_applicant, review.name, _("Linked to {0}.").format(target))
	else:
		set_outcome(review.upload_row, "Created", review.new_applicant, review.name, _("Not a duplicate: {0}").format(review.note))
	refresh_status(review.applicant_upload)


def set_outcome(row, status, applicant, review, message):
	values = {"status": status, "applicant": applicant, "message": allotment_import.mask_numbers(message)[:500]}
	if review:
		values["review"] = review
	frappe.db.set_value(ROW, row, values)


def refresh_status(name):
	"""Once no row waits for the import: Awaiting Review, Completed with errors or Completed."""
	counts = refresh_summary(name)
	if frappe.db.get_value(UPLOAD, name, "status") not in ("Importing", "Awaiting Review"):
		return
	if any(counts.get(s) for s in QUEUED):
		return
	if counts.get("Held for Review"):
		status = "Awaiting Review"
	elif set(counts) - set(DONE):
		status = "Completed with errors"
	else:
		status = "Completed"
	frappe.db.set_value(UPLOAD, name, "status", status)
	discard_raw_data(name)


def discard_raw_data(name):
	"""Nothing is left to import: drop the rows' file values and the file itself (its sha256 stays)."""
	frappe.db.set_value(ROW, {"applicant_upload": name}, "values_json", None, update_modified=False)
	allotment_import.discard_file(name, UPLOAD, "upload_file")


def reconcile(name):
	"""Finish an upload whose bulk run ended while rows still wait (a lost transaction, a failed run).

	Each such row becomes an Error row asking for a new upload (the rows already imported show as Already
	Imported there), and the upload completes. A no-op unless it is Importing and its run has finished.
	"""
	upload = frappe.db.get_value(UPLOAD, name, ["status", "bulk_run"], as_dict=True, for_update=True)
	if not upload or upload.status != "Importing" or not upload.bulk_run:
		return
	if frappe.db.get_value("Bulk Run", upload.bulk_run, "status") not in ("Completed", "Completed with errors", "Failed"):
		return
	message = _("Not imported: the import was interrupted at this row. Upload the file again to retry it.")
	for row in frappe.get_all(ROW, {"applicant_upload": name, "status": ["in", QUEUED]}, pluck="name"):
		set_outcome(row, "Error", None, None, message)
	refresh_status(name)


def reconcile_finished_uploads():
	"""Scheduler (hourly): complete uploads whose bulk run has finished; one bad upload never stops the others."""
	for name in frappe.get_all(UPLOAD, {"status": "Importing"}, pluck="name"):
		try:
			reconcile(name)
			frappe.db.commit()
		except Exception:  # noqa: BLE001
			frappe.db.rollback()
			frappe.log_error(title=f"Applicant upload reconcile failed: {name}", message=frappe.get_traceback(with_context=False))


def refresh_summary(name):
	table = frappe.qb.DocType(ROW)
	rows = frappe.qb.from_(table).select(table.status, Count("*")).where(table.applicant_upload == name).groupby(table.status).run()
	counts = dict(rows)
	summary = ", ".join(f"{_(status)}: {count}" for status, count in sorted(counts.items()))
	frappe.db.set_value(UPLOAD, name, "summary", summary, update_modified=False)
	return counts


# ---- preview ------------------------------------------------------------------------------

class RowCheck:
	"""Preview of the rows of one upload, in file order; earlier rows are remembered to flag repeats."""

	def __init__(self, upload):
		self.upload = upload
		self.keys, self.names, self.register_nos, self.emails = {}, {}, {}, {}

	def preview(self, row_no, values):
		"""(status, applicant, message) of one row, without writing anything."""
		missing = [label for label in REQUIRED if not values.get(COLUMNS[label])]
		if missing:
			return "Invalid", None, _("Required: {0}.").format(", ".join(_(label) for label in missing))
		try:
			fields = applicant_fields(self.upload, values)
		except Exception as e:  # noqa: BLE001 - a malformed cell makes the row invalid
			return "Invalid", None, cstr(e)
		key = key_of(fields)
		if key in self.keys:
			return "Invalid", None, _("Repeats row {0}.").format(self.keys[key])
		self.keys[key] = row_no
		existing = frappe.db.get_value("Student Applicant", {"oc_candidate_key": key}, "name")
		if existing:
			return "Already Imported", existing, _("Already imported.")
		email_problem = self.email_in_use(row_no, fields.get("student_email_id"))
		if email_problem:
			return "Invalid", None, email_problem
		earlier = self.earlier_row(row_no, fields)
		status, message = dry_run(fields)
		if status == "Valid" and earlier:
			return "Possible Duplicate", None, _("Same candidate as row {0}?").format(earlier)
		return status, None, message

	def email_in_use(self, row_no, email):
		"""Applicant e-mail is unique: a repeat in the file or an e-mail already held fails the insert."""
		if not email:
			return None
		if email.lower() in self.emails:
			return _("The e-mail is also on row {0}.").format(self.emails[email.lower()])
		self.emails[email.lower()] = row_no
		if frappe.db.exists("Student Applicant", {"student_email_id": email}):
			return _("Another applicant already has this e-mail address.")
		return None

	def earlier_row(self, row_no, fields):
		"""An earlier row with the same name and birth date, or the same register number of a compatible exam."""
		name = (duplicates.name_key(fields.get("first_name"), fields.get("middle_name"), fields.get("last_name")), str(fields["date_of_birth"]))
		exam = duplicates.id_key(fields["oc_qualifying_exam"])
		same_number = self.register_nos.setdefault(duplicates.id_key(fields["oc_qualifying_register_no"]), [])
		earlier = self.names.get(name) or next((row for other, row in same_number if duplicates.same_exam(other, exam)), None)
		self.names.setdefault(name, row_no)
		same_number.append((exam, row_no))
		return earlier


def dry_run(fields):
	"""(status, message) of the Student Applicant validation run in memory; any write it makes is rolled back."""
	doc = frappe.get_doc({"doctype": "Student Applicant", **fields})
	doc.flags.advisory_duplicate_check = True  # the preview writes nothing: no gap locks
	messages = len(frappe.message_log)
	frappe.db.savepoint(DRY_RUN)
	try:
		doc.set("__islocal", True)  # the steps of Document.insert up to the write
		doc._set_defaults()
		doc.set_docstatus()
		doc.check_if_latest()
		doc.set_new_name()  # the checklist rows built by validate need a parent; the name goes back with the rollback
		doc.set_parent_in_children()
		doc._validate_links()
		doc.run_before_save_methods()
		doc._validate()
	except duplicates.DuplicateCandidateError as error:
		return "Possible Duplicate", cstr(error)
	except frappe.ValidationError as error:
		return "Invalid", cstr(error)
	finally:
		frappe.db.rollback(save_point=DRY_RUN)
		del frappe.message_log[messages:]
	return "Valid", ""


# ---- file and values ----------------------------------------------------------------------

def file_rows(rows):
	"""[(sheet row no, {fieldname: text})] of the data rows; the template columns are checked first."""
	if not rows:
		frappe.throw(_("The upload file is empty."))
	labels = {label.lower(): field for label, field in COLUMNS.items()}
	header = [labels.get(cell.lower()) for cell in rows[0]]
	missing = [label for label in REQUIRED if COLUMNS[label] not in header]
	if missing:
		frappe.throw(_("The upload file is missing the template columns: {0}").format(", ".join(missing)))
	data = []
	for row_no, cells in enumerate(rows[1:], start=2):
		if any(cells):
			data.append((row_no, {field: cell for field, cell in zip(header, cells, strict=False) if field and cell}))
	return data


def applicant_fields(upload, values):
	"""The Student Applicant values of a row: the file's values as stored, plus the upload's company and year."""
	fields = {field: allotment_import.coerce(field, value) for field, value in values.items()}
	return {**fields, "oc_company": upload.company, "academic_year": upload.academic_year, "application_status": "Applied"}


def key_of(fields):
	return duplicates.candidate_key(
		fields["oc_qualifying_register_no"], fields["oc_qualifying_exam"], fields["date_of_birth"], fields["program"], fields["academic_year"]
	)


def save_row(upload, row_no, values, status, applicant, message):
	name = " ".join(filter(None, (values.get(f) for f in ("first_name", "middle_name", "last_name"))))
	frappe.get_doc(
		{
			"doctype": ROW, "applicant_upload": upload.name, "company": upload.company, "row_no": row_no, "candidate": name[:140], "status": status,
			"applicant": applicant, "message": allotment_import.mask_numbers(message)[:500], "values_json": json.dumps(values),
		}
	).insert(ignore_permissions=True)  # fmt: skip
