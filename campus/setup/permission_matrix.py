"""PR-05 Role-permission matrix: dumps every campus role's permissions on every campus DocType and report to
docs/usage/permission-matrix.csv, and fails loudly when a rule below is broken.

    bench --site <site> execute campus.setup.permission_matrix.run

Rules (each a defect line naming the DocType or Report and the role):
- only System Manager may delete a record kept for history: a submittable campus DocType or one in HISTORY_KEPT,
  unless it is in HISTORY_EXEMPT;
- student-facing roles (Student, Guardian, Guest and every role without desk access) read only the DocTypes in STUDENT_READABLE, write
  only those in STUDENT_WRITABLE, never delete, share or export, and open no Report;
- a confidential DocType (the restricted-record hook list, CO Attainment Snapshot, the exam-confidential set) and
  every Report on one is readable only by the roles listed for it in CONFIDENTIAL_READERS.
The rules read the permissions the site resolves (Custom DocPerm included), so run them on a migrated site.
"""

import csv
import os

import frappe
from frappe import _

FLAGS = (
	"read", "write", "create", "delete", "submit", "cancel", "amend", "report", "select", "import", "export",
	"print", "email", "share", "if_owner",
)  # fmt: skip
OWNER = "System Manager"
# Student and Guardian have desk_access = 0 (campus.campus_platform.portal_roles); they are still named so the matrix
# does not depend on the flag. Any other role without desk access (a future Applicant or Alumni role) is student-facing too.
STUDENT_FACING = ("Student", "Guardian", "Guest")
# Test-fixture DocTypes: part of the app so tests can use them, but not a permission of the product.
TEST_ONLY_DOCTYPES = ("Approval Test Document", "Campus Test Rule")  # Campus Test Rule: a stale test-site leftover, not in the app

# Lifecycle, official documents, results, certificates and the financial / audit ledgers: kept as history.
# Round Result (a placement round's shortlist) is deliberately not listed: the Placement Officer deletes a wrongly
# created one (commit 7c53906).
HISTORY_KEPT = (
	"Lifecycle Transition", "Official Document", "Completion Check", "Verifiable Document",
	"Student Result", "Result Ratification", "Mark Sheet Entry",
	"Hall Ticket", "Certificate Request", "Utilisation Certificate",
	"Grant Receipt", "Grant Interest", "Grant Income Recognition", "Scholarship Disbursement", "Fee Refund",
	"Fine Applied", "No Dues Clearance",
	"Aadhaar Access Log", "QP Access Log", "Seat Override Log", "Message Log",
	"Regulator Submission", "Question Paper",
)  # fmt: skip
# Submittable campus DocTypes are history too (a cancelled document stays) unless listed here. Name the reason.
HISTORY_EXEMPT = ()
# Ruled (PR-05), deliberately not in HISTORY_KEPT: Bank Collection Import / Row, Convocation List and University Result
# Import stay deletable (Accounts Manager / COE) only before they write anything; each controller's on_trash refuses
# once a Payment Entry, a lifecycle transition or a result was written from it.

# What a student, guardian or guest may open on the desk (the portal reads through its own API).
STUDENT_READABLE = (
	"Certificate Request", "Circular", "Condonation Request", "Hall Ticket", "Student Grievance", "Student Result",
)  # fmt: skip
# What a student-facing role may also create or change on the desk (own records: the Student role's rows are if_owner).
STUDENT_WRITABLE = ("Condonation Request", "Student Grievance")
# Reports a student-facing role may open: none, the portal reads through its own API.
STUDENT_READABLE_REPORTS = ()

_MENTORING = ("Mentor", "Class Advisor", "Dean Student Affairs", "HOD", "Principal")
_EXAM_CONFIDENTIAL = ("Exam Confidential", "COE", "Examiner")
CONFIDENTIAL_READERS = {
	"Counselling Note": ("Mentor", "Student Counsellor", "HOD", "Principal"),
	"Parent Interaction": _MENTORING,
	"CO Attainment Snapshot": ("COE", "Dean Academics"),
	"Answer Script Bundle": _EXAM_CONFIDENTIAL,
	"Dummy Number Map": _EXAM_CONFIDENTIAL,
	"QP Access Log": _EXAM_CONFIDENTIAL,
	"QP Setter Nomination": _EXAM_CONFIDENTIAL,
	"Question Bank Item": _EXAM_CONFIDENTIAL,
	"Question Paper": _EXAM_CONFIDENTIAL,
	"Question Paper Settings": _EXAM_CONFIDENTIAL,
	"Valuation Allocation": _EXAM_CONFIDENTIAL,
	"Valuation Entry": _EXAM_CONFIDENTIAL,
}  # fmt: skip


def run(path=None):
	"""Write the CSV and raise when a rule is broken. Returns the number of rows written."""
	rows = collect_rows()
	write_csv(rows, path or default_path())
	defects = find_defects(rows, frappe.get_hooks("restricted_record_doctypes") or [])
	if defects:
		frappe.throw("<br>".join(defects), title=_("Permission defects"))
	print(f"{len(rows)} permission rows written, no defects")
	return len(rows)


def default_path():
	return os.path.join(frappe.get_app_path("campus", "..", "docs", "usage"), "permission-matrix.csv")


def campus_modules():
	with open(frappe.get_app_path("campus", "modules.txt")) as modules:
		return [line.strip() for line in modules if line.strip()]


def collect_rows():
	"""One row per (kind, name, role, permlevel); kind is DocType or Report. Sorted for a stable diff.

	DocType rows carry `submittable`; every row carries `portal` (the role has no desk access); Report rows carry
	`ref_doctype`. A Report with no roles of its own is open to the roles that can read its reference DocType.
	"""
	modules = campus_modules()
	portal_roles = {*STUDENT_FACING, *frappe.get_all("Role", {"desk_access": 0}, pluck="name")}
	rows = []
	doctypes = frappe.get_all("DocType", {"module": ["in", modules], "name": ["not in", TEST_ONLY_DOCTYPES]}, pluck="name")
	for doctype in doctypes:
		meta = frappe.get_meta(doctype)
		rows += [doctype_row(meta, perm) for perm in meta.permissions]
	for report in frappe.get_all("Report", filters={"module": ["in", modules]}, fields=["name", "ref_doctype"]):
		rows += report_rows(report)
	for row in rows:
		row["portal"] = int(row["role"] in portal_roles)
	return sorted(rows, key=lambda r: (r["kind"], r["name"], r["role"], r["permlevel"]))


def doctype_row(meta, perm):
	row = {"kind": "DocType", "name": meta.name, "role": perm.role, "permlevel": perm.permlevel or 0}
	return row | {flag: int(bool(perm.get(flag))) for flag in FLAGS} | {"submittable": int(bool(meta.is_submittable))}


def report_rows(report):
	roles = frappe.get_all("Has Role", {"parent": report.name, "parenttype": "Report"}, pluck="role")
	if not roles and report.ref_doctype:
		roles = [p.role for p in frappe.get_meta(report.ref_doctype).permissions if p.read and not p.permlevel]
	base = {"kind": "Report", "name": report.name, "permlevel": 0, "read": 1, "ref_doctype": report.ref_doctype}
	return [base | {"role": role} for role in sorted(set(roles))]


COLUMNS = ["kind", "name", "ref_doctype", "role", "permlevel", *FLAGS, "submittable", "portal"]


def write_csv(rows, path):
	blank = {"ref_doctype": "", "submittable": 0, **dict.fromkeys(FLAGS, 0)}
	with open(path, "w", newline="") as out:
		writer = csv.DictWriter(out, COLUMNS, extrasaction="ignore", lineterminator="\n")
		writer.writeheader()
		writer.writerows(blank | row for row in rows)


def find_defects(rows, restricted_doctypes):
	"""Pure over the rows (see collect_rows), so each rule is testable with synthetic rows."""
	doctype_rows = [row for row in rows if row["kind"] == "DocType"]
	report_rows = [row for row in rows if row["kind"] == "Report"]
	return (
		history_defects(doctype_rows)
		+ student_defects(doctype_rows)
		+ confidential_defects(doctype_rows, restricted_doctypes)
		+ report_defects(report_rows)
	)


def is_student_facing(row):
	return row["role"] in STUDENT_FACING or bool(row.get("portal"))


def is_history(row):
	if row["name"] in HISTORY_EXEMPT:
		return False
	return row["name"] in HISTORY_KEPT or bool(row.get("submittable"))


def history_defects(rows):
	return [
		f"{row['name']}: {row['role']} can delete a record kept for history"
		for row in rows
		if is_history(row) and row.get("delete") and row["role"] != OWNER
	]


def student_defects(rows):
	defects = []
	for row in (r for r in rows if is_student_facing(r)):
		name, role = row["name"], row["role"]
		if row.get("read") and name not in STUDENT_READABLE:
			defects.append(f"{name}: {role} can read a staff-only DocType")
		for flag in ("write", "create"):
			if row.get(flag) and name not in STUDENT_WRITABLE:
				defects.append(f"{name}: {role} can {flag}")
		for flag in ("delete", "share", "export"):
			if row.get(flag):
				defects.append(f"{name}: {role} can {flag}")
	return defects


def report_defects(rows):
	defects = []
	for row in rows:
		name, role, readers = row["name"], row["role"], CONFIDENTIAL_READERS.get(row.get("ref_doctype"))
		if is_student_facing(row) and name not in STUDENT_READABLE_REPORTS:
			defects.append(f"{name}: {role} can open a staff-only Report")
		elif readers is not None and role not in (*readers, OWNER):
			defects.append(f"{name}: {role} can open a Report on a confidential DocType")
	return defects


def confidential_defects(rows, restricted_doctypes):
	defects = [
		f"{name}: restricted record without a reader list"
		for name in restricted_doctypes
		if name not in CONFIDENTIAL_READERS
	]
	for row in rows:
		readers = CONFIDENTIAL_READERS.get(row["name"])
		if readers is not None and row.get("read") and row["role"] not in (*readers, OWNER):
			defects.append(f"{row['name']}: {row['role']} can read a confidential DocType")
		if row["role"] == "Exam Confidential" and row["name"] not in CONFIDENTIAL_READERS:
			defects.append(f"{row['name']}: exam-confidential DocType without a reader list")
	return defects
