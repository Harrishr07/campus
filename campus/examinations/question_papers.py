"""M06-03 Confidential question papers: who may open them, when, and the log of every attempt.

Only the "Exam Confidential" role reaches Question Paper, Question Bank Item, QP Setter Nomination and QP Access
Log: the DocType permissions name no other role, and the has_permission / permission-query hooks below refuse every
user without it (System Manager included), so a Custom DocPerm cannot open them either. Sharing them is refused.

An Approved (sealed) paper is closed to everybody until its download window opens (Question Paper Settings: the
lead minutes before release_at; the window ends with the slot). Its PDFs are encrypted at rest
(question_paper_files) and leave the server only through `download_paper`: inside the window, to Exam
Confidential, watermarked with the user and the time. Printing copies for a hall is recorded by `print_copies`.

Every attempt to open (desk/API read or print), download or print a paper is written to QP Access Log, allowed
or denied, with user, time and IP. The endpoints answer a denial with HTTP 403 and commit the log; a denial
inside a permission check is queued (deferred insert, like Frappe's Access Log) since the request rolls back.

Administrator bypasses Frappe's permission checks altogether; the encrypted PDF and the endpoint's window check
still apply to it.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, format_datetime, get_datetime, now_datetime

from campus.examinations.question_paper_files import PAPER_FILE_FIELDS, read_sealed, watermark
from campus.examinations.question_paper_rules import in_window, release_window

EXAM_CONFIDENTIAL = "Exam Confidential"
QUESTION_PAPER = "Question Paper"
SEALED = "Approved"
CONFIDENTIAL_DOCTYPES = ("Question Bank Item", "QP Setter Nomination", "QP Access Log", QUESTION_PAPER)
LOGGED_PTYPES = {"read": "View", "print": "Print View"}
SETTINGS = "Question Paper Settings"


class QPAccessDenied(frappe.PermissionError):
	pass


def is_confidential_user(user):
	return EXAM_CONFIDENTIAL in frappe.get_roles(user)


# ---- the window -----------------------------------------------------------------------------


def window_of(doc):
	"""(opens, closes) of the paper's download window, from the current settings."""
	return release_window(get_datetime(doc.release_at), setting("download_lead_minutes"), setting("slot_minutes"))


def setting(field):
	return cint(frappe.db.get_single_value(SETTINGS, field))


def slot_start(exam_session, course):
	"""Start of the course's slot in the session's schedule, or None."""
	row = frappe.db.get_value("Exam Schedule", {"parent": exam_session, "parenttype": "Exam Session", "course": course},
		["exam_date", "slot"], as_dict=True)  # fmt: skip
	if not row or not row.exam_date:
		return None
	field = "forenoon_starts_at" if row.slot == "FN" else "afternoon_starts_at"
	return get_datetime(f"{row.exam_date} {frappe.db.get_single_value(SETTINGS, field)}")


def paper_access(doc, user):
	"""(allowed, reason) for opening the paper's record."""
	if not is_confidential_user(user):
		return False, _("Only Exam Confidential may open question papers.")
	if doc.moderation_status == SEALED and doc.release_at and now_datetime() < window_of(doc)[0]:
		return False, _("The paper is sealed until its download window opens.")
	return True, ""


def download_access(doc, user, paper_set):
	"""(allowed, reason) for downloading or printing set `paper_set` of the paper."""
	if not is_confidential_user(user):
		return False, _("Only Exam Confidential may download question papers.")
	if doc.moderation_status != SEALED:
		return False, _("Only an approved paper can be downloaded.")
	if not doc.release_at:
		return False, _("The paper has no release time.")
	opens, closes = window_of(doc)
	if not in_window(now_datetime(), opens, closes):
		return False, _("Downloads are open only from {0} to {1}.").format(format_datetime(opens), format_datetime(closes))
	if not doc.get(PAPER_FILE_FIELDS.get(paper_set, "")):
		return False, _("Set {0} has no paper attached.").format(paper_set)
	return True, ""


# ---- permission hooks -----------------------------------------------------------------------


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Question Paper: Exam Confidential only, and a sealed paper stays closed until its window. Logs reads."""
	user = user or frappe.session.user
	if ptype == "share":
		return False
	allowed, reason = paper_access(doc, user)
	if ptype in LOGGED_PTYPES and not doc.is_new():
		log_once(doc, LOGGED_PTYPES[ptype], allowed, reason, user)
	return allowed


def permission_query(user=None, doctype=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	if not is_confidential_user(user):
		return "1=0"
	cutoff = frappe.db.escape(str(add_to_date(now_datetime(), minutes=setting("download_lead_minutes"))))
	return f"(`tabQuestion Paper`.moderation_status != '{SEALED}' or `tabQuestion Paper`.release_at <= {cutoff})"


def confidential_has_permission(doc, ptype=None, user=None, debug=False):
	"""Question Bank Item, QP Setter Nomination, QP Access Log: Exam Confidential only; never shared."""
	return ptype != "share" and is_confidential_user(user or frappe.session.user)


def confidential_query(user=None, doctype=None):
	user = user or frappe.session.user
	return "" if user == "Administrator" or is_confidential_user(user) else "1=0"


def file_has_permission(doc, ptype=None, user=None, debug=False):
	"""A question paper's File is never read directly (it is ciphertext); the download endpoint serves it."""
	return doc.attached_to_doctype != QUESTION_PAPER or ptype in ("write", "create", "delete")


def block_confidential_share(doc, method=None):
	"""DocShare validate: Frappe lets a share grant what the permission hooks refuse, so none is allowed."""
	if doc.share_doctype in CONFIDENTIAL_DOCTYPES:
		frappe.throw(_("{0} documents are confidential and cannot be shared.").format(_(doc.share_doctype)))


# ---- the access log -------------------------------------------------------------------------


def log_access(doc, action, allowed, reason="", user=None, paper_set=None, room=None, copies=0, deferred=False):
	log = frappe.get_doc(
		{
			"doctype": "QP Access Log", "question_paper": doc.name, "company": doc.company, "paper_set": paper_set,
			"action": action, "result": "Allowed" if allowed else "Denied", "reason": reason or None,
			"user": user or frappe.session.user, "accessed_at": now_datetime(), "ip_address": getattr(frappe.local, "request_ip", None),
			"room": room, "copies": cint(copies),
		}
	)  # fmt: skip
	if deferred and not frappe.in_test:
		log.deferred_insert()
	else:
		log.insert(ignore_permissions=True)


def log_once(doc, action, allowed, reason, user):
	"""A permission check runs several times per request; one log row per request is enough."""
	if getattr(frappe.local, "request", None):
		key = (doc.name, action, user, allowed)
		seen = frappe.local.flags.setdefault("qp_access_logged", set())
		if key in seen:
			return
		seen.add(key)
	log_access(doc, action, allowed, reason, user, deferred=True)


# ---- download and print ---------------------------------------------------------------------


def open_paper(question_paper, paper_set="A"):
	"""The watermarked PDF of set `paper_set`; logs the attempt and raises QPAccessDenied when refused."""
	doc = frappe.get_doc(QUESTION_PAPER, question_paper)
	user = frappe.session.user
	allowed, reason = download_access(doc, user, paper_set)
	log_access(doc, "Download", allowed, reason, user, paper_set=paper_set)
	if not allowed:
		raise QPAccessDenied(reason)
	stamp = _("{0} | {1} | {2} Set {3}").format(user, now_datetime().strftime("%Y-%m-%d %H:%M:%S"), doc.name, paper_set)
	return watermark(read_sealed(doc.get(PAPER_FILE_FIELDS[paper_set])), stamp)


def print_copies(question_paper, paper_set, room, copies):
	"""Record `copies` printed for hall `room`; same access as a download. Returns the hall's total for the set."""
	copies = cint(copies)
	if copies <= 0:
		frappe.throw(_("Enter the number of copies printed."))
	if not frappe.db.exists("Room", room):
		frappe.throw(_("Hall {0} does not exist.").format(room))
	doc = frappe.get_doc(QUESTION_PAPER, question_paper)
	user = frappe.session.user
	allowed, reason = download_access(doc, user, paper_set)
	log_access(doc, "Print", allowed, reason, user, paper_set=paper_set, room=room, copies=copies)
	if not allowed:
		raise QPAccessDenied(reason)
	filters = {"question_paper": doc.name, "paper_set": paper_set, "room": room, "action": "Print", "result": "Allowed"}
	return sum(frappe.get_all("QP Access Log", filters, pluck="copies"))


@frappe.whitelist(methods=["GET"])
def download_paper(question_paper, paper_set="A"):
	"""Send the watermarked PDF inside the download window; HTTP 403 otherwise. The log row is kept either way."""
	frappe.local.flags.commit = True  # a GET is rolled back unless flagged: the log must survive
	try:
		content = open_paper(question_paper, paper_set)
	except QPAccessDenied as denied:
		deny(denied)
		return
	frappe.local.response.update(
		{"type": "download", "filename": f"{question_paper}-set-{paper_set.lower()}.pdf", "filecontent": content}
	)


@frappe.whitelist(methods=["POST"])
def record_print(question_paper, paper_set, room, copies):
	"""Record copies printed for a hall; HTTP 403 outside the window (the log row is kept)."""
	try:
		return print_copies(question_paper, paper_set, room, copies)
	except QPAccessDenied as denied:
		deny(denied)


def deny(denied):
	frappe.local.response.http_status_code = 403
	frappe.msgprint(str(denied), title=_("Not Permitted"), indicator="red")
