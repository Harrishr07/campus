"""M06-03 Confidential question papers: who may open them, when, and the log of every attempt.

Only the "Exam Confidential" role reaches Question Paper, Question Bank Item, QP Setter Nomination and QP Access
Log: the DocType permissions name no other role, and the has_permission / permission-query hooks below refuse every
user without it (System Manager included), so a Custom DocPerm cannot open them either. Sharing them is refused.

A paper is sealed when the moderation approval (Phase-1 approval engine) submits it. Approval snapshots its download
window (release_at minus the lead minutes, to the end of the slot) onto the paper, so a later Settings edit changes
nothing. A sealed paper is closed to everybody until that window opens; while it is, the whole bank of its course is
hidden and locked alike (no oracle of which items are on it), and its own items are never editable again. Its PDFs are encrypted at rest (question_paper_files) and leave the server only through
`download_paper` (POST, not cached): inside the window, to Exam Confidential, watermarked with the user and the
time. Printing copies for an exam hall of the college is recorded by `record_print`. `withdraw` (COE or System
Manager of the college, with a reason) retires a paper for good: a withdrawn sealed paper stays closed forever.

Every attempt to open (desk/API read or print, the desk form for every user including Administrator), list without
the role (once a minute per user), download, print or withdraw a paper is written to QP Access Log, allowed or
denied, with user, time and IP. The rows of a transaction are also buffered; if it rolls back (a denied request
does), one after_rollback flush writes them all again and commits once, so a denial is never lost.

System Manager configuration paths (backups, Jinja templates, Customize Form, Server Scripts, self-granted roles)
are Administrator-equivalent: a documented residual (docs/rulings.md). Version, Notification and Webhook records on
these DocTypes are refused.

Administrator bypasses Frappe's permission checks altogether; its desk opens are still logged, the questions of a
sealed paper are stripped from the desk form, and the encrypted PDF and the endpoint's window check still apply.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, format_datetime, get_datetime, now_datetime

from campus.examinations.exam_halls import EXAM_HALL
from campus.examinations.question_paper_files import PAPER_FILE_FIELDS, QPFileError, read_sealed, watermark
from campus.examinations.question_paper_rules import in_window, release_window

EXAM_CONFIDENTIAL = "Exam Confidential"
QUESTION_PAPER = "Question Paper"
BANK_ITEM = "Question Bank Item"
LOG = "QP Access Log"
APPROVED = "Approved"
WITHDRAWN = "Withdrawn"
CONFIDENTIAL_DOCTYPES = (BANK_ITEM, "QP Setter Nomination", LOG, QUESTION_PAPER)
LOGGED_PTYPES = {"read": "View", "print": "Print View"}
READ_PTYPES = ("read", "select", "print", "email", "export", "report")
SETTINGS = "Question Paper Settings"
LIST_DENIAL_CACHE = "campus-qp-list-denied"


class QPAccessDenied(frappe.PermissionError):
	pass


def is_confidential_user(user):
	return EXAM_CONFIDENTIAL in frappe.get_roles(user)


# ---- the window -----------------------------------------------------------------------------


def setting(field):
	return cint(frappe.db.get_single_value(SETTINGS, field))


def window_for(release_at):
	"""(opens, closes) for `release_at` under the current settings: what approval snapshots onto the paper."""
	return release_window(get_datetime(release_at), setting("download_lead_minutes"), setting("slot_minutes"))


def slot_start(exam_session, course):
	"""Start of the course's slot in the session's schedule, or None (no schedule row, or no slot time set)."""
	row = frappe.db.get_value("Exam Schedule", {"parent": exam_session, "parenttype": "Exam Session", "course": course},
		["exam_date", "slot"], as_dict=True)  # fmt: skip
	if not row or not row.exam_date:
		return None
	starts_at = frappe.db.get_single_value(SETTINGS, "forenoon_starts_at" if row.slot == "FN" else "afternoon_starts_at")
	return get_datetime(f"{row.exam_date} {starts_at}") if starts_at else None


def is_closed(doc, now=None):
	"""A sealed (approved) paper whose snapshotted window has not opened yet, or a withdrawn sealed paper (for good)."""
	if doc.docstatus == 2:
		return True
	opens = doc.get("download_opens_at")
	return doc.docstatus == 1 and (not opens or (now or now_datetime()) < get_datetime(opens))


def paper_access(doc, user):
	"""(allowed, reason) for opening the paper's record."""
	if not is_confidential_user(user):
		return False, _("Only Exam Confidential may open question papers.")
	if is_closed(doc):
		return False, _("The paper is sealed until its download window opens.")
	return True, ""


def download_access(doc, user, paper_set):
	"""(allowed, reason) for downloading or printing set `paper_set` of the paper."""
	if not is_confidential_user(user):
		return False, _("Only Exam Confidential may download question papers.")
	if doc.docstatus != 1:
		return False, _("Only an approved paper can be downloaded; this one is {0}.").format(_(doc.moderation_status))
	opens, closes = get_datetime(doc.download_opens_at), get_datetime(doc.download_closes_at)
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
		log_list_denial(user)
		return "1=0"
	now = frappe.db.escape(str(now_datetime()))
	return f"(`tabQuestion Paper`.docstatus = 0 or (`tabQuestion Paper`.docstatus = 1 and `tabQuestion Paper`.download_opens_at <= {now}))"


def confidential_has_permission(doc, ptype=None, user=None, debug=False):
	"""QP Setter Nomination, QP Access Log: Exam Confidential only; never shared."""
	return ptype != "share" and is_confidential_user(user or frappe.session.user)


def confidential_query(user=None, doctype=None):
	user = user or frappe.session.user
	return "" if user == "Administrator" or is_confidential_user(user) else "1=0"


def bank_item_has_permission(doc, ptype=None, user=None, debug=False):
	"""Question Bank Item: Exam Confidential only. While any sealed paper of the course is closed, every item of the
	course is hidden and locked alike (hiding only the paper's items would show which questions are on it); an item
	used by a sealed paper is never changed again."""
	if not confidential_has_permission(doc, ptype, user):
		return False
	if course_closed(doc.company, doc.course):
		return False
	if ptype in READ_PTYPES or doc.is_new():
		return True
	return not frappe.db.sql(
		"""select 1 from `tabQuestion Paper Question` q join `tabQuestion Paper` p on p.name = q.parent
		and q.parenttype = 'Question Paper' where q.question_item = %s and p.docstatus = 1 limit 1""",
		doc.name,
	)  # fmt: skip


def bank_item_query(user=None, doctype=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	if not is_confidential_user(user):
		return "1=0"
	return f"""not exists (select 1 from `tabQuestion Paper` p where {closed_paper_sql()}
		and p.company = `tabQuestion Bank Item`.company and p.course = `tabQuestion Bank Item`.course)"""


def closed_paper_sql():
	now = frappe.db.escape(str(now_datetime()))
	return f"p.docstatus = 1 and (p.download_opens_at is null or p.download_opens_at > {now})"


def course_closed(company, course):
	"""Whether a sealed paper of `course` in `company` has not reached its download window."""
	return bool(frappe.db.sql(f"select 1 from `tabQuestion Paper` p where {closed_paper_sql()} and p.company = %s and p.course = %s limit 1",
		(company, course)))  # fmt: skip


def file_has_permission(doc, ptype=None, user=None, debug=False):
	"""A question paper's File is never read directly (it is ciphertext; the download endpoint serves it), and once
	the paper leaves draft its Files can no longer be changed or removed."""
	if doc.attached_to_doctype != QUESTION_PAPER:
		return True
	if ptype not in ("write", "create", "delete"):
		return False
	return not cint(frappe.db.get_value(QUESTION_PAPER, doc.attached_to_name, "docstatus"))


UNVERSIONED = (BANK_ITEM, QUESTION_PAPER, "QP Setter Nomination")


def refuse_confidential_version(doc, method=None):
	"""Version before_insert: a Version would copy confidential fields into a table System Managers read."""
	if doc.ref_doctype in UNVERSIONED:
		frappe.throw(_("{0} keeps no version history (confidential).").format(_(doc.ref_doctype)))


def refuse_confidential_notification(doc, method=None):
	"""Notification validate: a template could mail confidential fields out."""
	if doc.document_type in CONFIDENTIAL_DOCTYPES:
		frappe.throw(_("Notifications cannot be set on {0} (confidential).").format(_(doc.document_type)))


def refuse_confidential_webhook(doc, method=None):
	"""Webhook validate: a webhook would post confidential documents to another server."""
	if doc.webhook_doctype in CONFIDENTIAL_DOCTYPES:
		frappe.throw(_("Webhooks cannot be set on {0} (confidential).").format(_(doc.webhook_doctype)))


def block_confidential_share(doc, method=None):
	"""DocShare validate: Frappe lets a share grant what the permission hooks refuse, so none is allowed."""
	if doc.share_doctype in CONFIDENTIAL_DOCTYPES:
		frappe.throw(_("{0} documents are confidential and cannot be shared.").format(_(doc.share_doctype)))


# ---- the access log -------------------------------------------------------------------------


def log_access(doc, action, allowed, reason="", user=None, paper_set=None, room=None, copies=0):
	"""Write a QP Access Log row now, and again after a rollback of this transaction (a denied request rolls back)."""
	values = {
		"doctype": LOG, "question_paper": doc and doc.name, "company": doc and doc.company, "paper_set": paper_set,
		"action": action, "result": "Allowed" if allowed else "Denied", "reason": reason or None,
		"user": user or frappe.session.user, "accessed_at": now_datetime(), "ip_address": getattr(frappe.local, "request_ip", None),
		"room": room, "copies": cint(copies),
	}  # fmt: skip
	insert_log(values)
	keep_for_rollback(values)


def insert_log(values):
	log = frappe.get_doc(dict(values))
	log.flags.ignore_links = True
	log.insert(ignore_permissions=True)


def keep_for_rollback(values):
	"""Buffer the row for this transaction; one flush after a rollback writes them all and commits once."""
	buffer = getattr(frappe.local, "qp_log_buffer", None)
	if buffer is None:
		buffer = frappe.local.qp_log_buffer = []
		frappe.db.after_rollback.add(flush_after_rollback)
		frappe.db.after_commit.add(drop_buffer)  # committed: the rows are already in
	buffer.append(values)


def flush_after_rollback():
	rows = getattr(frappe.local, "qp_log_buffer", None) or []
	frappe.local.qp_log_buffer = None
	if not rows:
		return
	for values in rows:
		insert_log(values)
	frappe.db.commit()


def drop_buffer():
	frappe.local.qp_log_buffer = None


def log_once(doc, action, allowed, reason, user):
	"""A permission check runs several times per request; one log row per request is enough."""
	if getattr(frappe.local, "request", None):
		key = (doc.name, action, user, allowed)
		seen = frappe.local.flags.setdefault("qp_access_logged", set())
		if key in seen:
			return
		seen.add(key)
	log_access(doc, action, allowed, reason, user)


def log_list_denial(user):
	"""A list or report of question papers without the role: one row per user per minute."""
	key = f"{LIST_DENIAL_CACHE}:{user}"
	if frappe.cache.get_value(key):
		return
	frappe.cache.set_value(key, 1, expires_in_sec=60)
	log_access(None, "List", False, _("Only Exam Confidential may list question papers."), user)


# ---- download, print, withdraw --------------------------------------------------------------


def open_paper(question_paper, paper_set="A"):
	"""The watermarked PDF of set `paper_set`; logs the attempt and raises QPAccessDenied when refused."""
	doc = frappe.get_doc(QUESTION_PAPER, question_paper)
	user = frappe.session.user
	allowed, reason = download_access(doc, user, paper_set)
	content = None
	if allowed:
		try:
			content = read_sealed(doc, PAPER_FILE_FIELDS[paper_set])
		except QPFileError as error:
			allowed, reason = False, str(error)
	log_access(doc, "Download", allowed, reason, user, paper_set=paper_set)
	if not allowed:
		raise QPAccessDenied(reason)
	stamp = _("{0} | {1} | {2} Set {3}").format(user, now_datetime().strftime("%Y-%m-%d %H:%M:%S"), doc.name, paper_set)
	return watermark(content, stamp)


def print_copies(question_paper, paper_set, room, copies):
	"""Record `copies` printed for exam hall `room`; same access as a download. Returns the hall's total for the set."""
	copies = cint(copies)
	if copies <= 0:
		frappe.throw(_("Enter the number of copies printed."))
	doc = frappe.get_doc(QUESTION_PAPER, question_paper)
	hall = frappe.db.get_value("Room", room, ["oc_room_type", "oc_company"], as_dict=True)
	if not hall or hall.oc_room_type != EXAM_HALL or hall.oc_company != doc.company:
		frappe.throw(_("{0} is not an Exam Hall of {1}.").format(room, doc.company))
	user = frappe.session.user
	allowed, reason = download_access(doc, user, paper_set)
	log_access(doc, "Print", allowed, reason, user, paper_set=paper_set, room=room, copies=copies)
	if not allowed:
		raise QPAccessDenied(reason)
	filters = {"question_paper": doc.name, "paper_set": paper_set, "room": room, "action": "Print", "result": "Allowed"}
	return sum(frappe.get_all(LOG, filters, pluck="copies"))


@frappe.whitelist(methods=["POST"])
def download_paper(question_paper, paper_set="A"):
	"""Send the watermarked PDF inside the download window; HTTP 403 otherwise. The log row is kept either way."""
	frappe.local.response_headers.set("Cache-Control", "no-store")
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


WITHDRAW_ROLES = ("COE", "System Manager")


@frappe.whitelist(methods=["POST"])
def withdraw(question_paper, reason):
	"""Withdraw a paper for good (COE or System Manager of the paper's college, any time, with a reason): a sealed
	paper is cancelled and stays closed, a draft is closed."""
	withdraw_doc(frappe.get_doc(QUESTION_PAPER, question_paper), reason)


@frappe.whitelist(methods=["POST"])
def withdraw_course_paper(exam_session, course, reason):
	"""Withdraw the live papers of `course` in `exam_session` without opening them (COE or System Manager of the
	session's college, with a reason); returns their names."""
	company = frappe.db.get_value("Exam Session", exam_session, "company")
	if not may_withdraw(frappe.session.user, company):
		raise frappe.PermissionError(_("Only the COE or a System Manager of {0} may withdraw its question papers.").format(company))
	names = frappe.get_all(QUESTION_PAPER, {"exam_session": exam_session, "course": course, "docstatus": ["<", 2],
		"moderation_status": ["!=", WITHDRAWN]}, pluck="name", order_by="name")  # fmt: skip
	for name in names:
		withdraw_doc(frappe.get_doc(QUESTION_PAPER, name), reason)
	return names


def withdraw_doc(doc, reason):
	reason = (reason or "").strip()
	if not may_withdraw(frappe.session.user, doc.company):
		raise frappe.PermissionError(_("Only the COE or a System Manager of {0} may withdraw its question papers.").format(doc.company))
	if not reason:
		frappe.throw(_("Give the reason for withdrawing the paper."))
	if doc.docstatus == 2 or doc.moderation_status == WITHDRAWN:
		return
	doc.flags.ignore_permissions = doc.flags.ignore_approval_lock = True
	if doc.docstatus == 1:
		retire_questions(doc)
		doc.cancel()
		doc.db_set("withdrawal_reason", reason)
	else:
		doc.moderation_status, doc.withdrawal_reason = WITHDRAWN, reason
		doc.save()
	log_access(doc, "Withdraw", True, reason)


def retire_questions(doc):
	"""The questions of a withdrawn sealed paper may have leaked: they never go on another paper."""
	for item in {q.question_item for q in doc.questions}:
		frappe.db.set_value(BANK_ITEM, item, {"disabled": 1, "retired_by_withdrawal": doc.name})


def may_withdraw(user, company):
	from frappe.permissions import get_user_permissions

	if user != "Administrator" and not set(WITHDRAW_ROLES) & set(frappe.get_roles(user)):
		return False
	allowed = [p.get("doc") for p in get_user_permissions(user).get("Company", [])]
	return not allowed or company in allowed


def deny(denied):
	frappe.local.response.http_status_code = 403
	frappe.msgprint(str(denied), title=_("Not Permitted"), indicator="red")
