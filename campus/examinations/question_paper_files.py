"""M06-03 Question paper files: the attached PDFs are encrypted at rest and only decrypted (and watermarked) by the
download endpoint inside the release window.

Frappe serves /private/files/ through the File controller's own permission check, which grants the uploader and
Administrator regardless of app hooks, so access control alone cannot keep a paper closed. On save, a plain PDF in
an Attach field is replaced by a private `.enc` File holding its Fernet ciphertext under the dedicated site key
`campus_qp_key` (not the shared encryption_key); a direct file URL then only ever returns ciphertext. The key is
read from the environment (CAMPUS_QP_KEY) first, then from a key file outside sites/ (site_config
`campus_qp_key_file`, so backups do not carry it), and only then from site_config itself.

Binding: the encrypted plaintext starts with a header naming the paper and the field, and the sealed File is
attached to (Question Paper, name, field). A `.enc` value is accepted, and decrypted, only when both match, so a
paper can neither point at nor copy another paper's sealed file, and a plain file named `.enc` is refused. Approval
also snapshots each sealed File's name and the SHA-256 of its ciphertext; an approved paper serves only that file.

Plaintext: only this paper's (or the uploader's unattached) plain upload is sealed, and an upload whose content
matches a File of another document is refused. The plain Files are deleted once the save commits; a daily sweep
removes any plain File left attached to a Question Paper.
"""

import hashlib
import io
import os
from functools import partial

import frappe
from cryptography.fernet import Fernet, InvalidToken
from frappe import _
from frappe.utils import add_to_date, get_bench_path, now_datetime
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

KEY_CONFIG = "campus_qp_key"
KEY_FILE_CONFIG = "campus_qp_key_file"
KEY_ENV = "CAMPUS_QP_KEY"
SEALED_SUFFIX = ".enc"
PAPER_FILE_FIELDS = {"A": "set_a_file", "B": "set_b_file"}
QUESTION_PAPER = "Question Paper"
SWEEP_AFTER_MINUTES = 60  # an upload not saved into its paper within this time is removed


class QPFileError(frappe.ValidationError):
	pass


def key():
	"""The question paper key: environment, else a key file outside sites/, else site_config; None when unset."""
	if os.environ.get(KEY_ENV):
		return os.environ[KEY_ENV].strip()
	path = frappe.conf.get(KEY_FILE_CONFIG)
	if path:
		real, sites = os.path.realpath(path), os.path.realpath(os.path.join(get_bench_path(), "sites"))
		if real == sites or real.startswith(sites + os.sep):
			frappe.throw(
				_("The question paper key file must be outside the bench's sites folder (it is backed up).")
			)
		with open(real) as f:
			return f.read().strip()
	return frappe.conf.get(KEY_CONFIG)


def cipher():
	value = key()
	if not value:
		frappe.throw(
			_("The question paper key is not configured ({0}, {1} or {2}).").format(
				KEY_ENV, KEY_FILE_CONFIG, KEY_CONFIG
			)
		)
	return Fernet(value.encode())


def binding(name, field):
	return f"campus-qp:{name}:{field}\n".encode()


# ---- sealing (Question Paper validate) ----------------------------------------------------


def seal_attachments(doc):
	"""Accept a bound sealed file or seal a new plain upload, for each paper file field of `doc`."""
	for field in PAPER_FILE_FIELDS.values():
		url = doc.get(field)
		if not url:
			continue
		if url.endswith(SEALED_SUFFIX):
			if not bound_file(doc, field):
				frappe.throw(_("{0} is not a sealed file of this paper.").format(url), QPFileError)
		else:
			doc.set(field, seal(doc, field, url))


def seal(doc, field, url):
	plain = plain_uploads(doc, field, url)
	if not plain:
		frappe.throw(_("Upload the paper file to this Question Paper ({0}).").format(url), QPFileError)
	file = frappe.get_doc("File", plain[0])
	content = file.get_content(encodings=[])
	if not isinstance(content, bytes) or not content.startswith(b"%PDF"):
		frappe.throw(_("Attach the question paper as a PDF."), QPFileError)
	if frappe.db.exists("File", {"content_hash": file.content_hash, "name": ["not in", plain]}):
		frappe.throw(
			_("This file is also attached elsewhere; upload the paper only to its Question Paper."),
			QPFileError,
		)
	sealed = frappe.get_doc(
		{
			"doctype": "File", "file_name": f"{doc.name}-{field}.pdf{SEALED_SUFFIX}", "is_private": 1,
			"content": cipher().encrypt(binding(doc.name, field) + content), "attached_to_doctype": QUESTION_PAPER,
			"attached_to_name": doc.name, "attached_to_field": field,
		}
	).insert(ignore_permissions=True)  # fmt: skip
	frappe.db.after_commit.add(partial(delete_files, plain))
	return sealed.file_url


def plain_uploads(doc, field, url):
	"""Files behind `url` that are this paper's upload for `field`, or the session user's unattached upload."""
	files = frappe.get_all(
		"File",
		{"file_url": url},
		["name", "owner", "attached_to_doctype", "attached_to_name", "attached_to_field"],
	)
	return [
		f.name for f in files
		if ((f.attached_to_doctype, f.attached_to_name) == (QUESTION_PAPER, doc.name) and f.attached_to_field in (field, None, ""))
		or (not f.attached_to_doctype and f.owner == frappe.session.user)
	]  # fmt: skip


def delete_files(names):
	"""Delete plain uploads; they are detached first, since an approved paper protects its attached Files."""
	for name in names:
		if frappe.db.exists("File", name):
			frappe.db.set_value(
				"File",
				name,
				{"attached_to_doctype": None, "attached_to_name": None, "attached_to_field": None},
			)
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)
	if not frappe.in_test:
		frappe.db.commit()  # after_commit runs once the save's transaction has committed


def sweep_plaintext():
	"""Daily: delete plain (not sealed) Files attached to a Question Paper and left unsaved."""
	cutoff = add_to_date(now_datetime(), minutes=-SWEEP_AFTER_MINUTES)
	names = frappe.get_all("File", {"attached_to_doctype": QUESTION_PAPER, "file_url": ["not like", f"%{SEALED_SUFFIX}"],
		"is_folder": 0, "creation": ["<", cutoff]}, pluck="name")  # fmt: skip
	delete_files(names)
	return len(names)


# ---- reading (download endpoint) ----------------------------------------------------------


def bound_file(doc, field):
	"""The sealed File of `doc`'s `field` when it is attached to this paper and field and decrypts to this binding."""
	url = doc.get(field)
	name = frappe.db.get_value("File", {"file_url": url, "attached_to_doctype": QUESTION_PAPER,
		"attached_to_name": doc.name, "attached_to_field": field})  # fmt: skip
	if not name or decrypt_bound(name, doc.name, field) is None:
		return None
	return name


def decrypt_bound(file_name, paper, field):
	try:
		plain = cipher().decrypt(frappe.get_doc("File", file_name).get_content(encodings=[]))
	except (InvalidToken, TypeError, ValueError):
		return None
	header = binding(paper, field)
	return plain[len(header) :] if plain.startswith(header) else None


def fingerprint(file_name):
	"""SHA-256 of the File's stored bytes (the ciphertext)."""
	with open(frappe.get_doc("File", file_name).get_full_path(), "rb") as f:
		return hashlib.sha256(f.read()).hexdigest()


def snapshot(doc):
	"""Fix each sealed File's name and fingerprint on `doc` (approval)."""
	for field in PAPER_FILE_FIELDS.values():
		name = doc.get(field) and bound_file(doc, field)
		doc.set(f"{field}_id", name or None)
		doc.set(f"{field}_sha256", (name and fingerprint(name)) or None)


def read_sealed(doc, field):
	"""The decrypted PDF of `doc`'s `field`; QPFileError unless it is this paper's own sealed file (and, once
	approved, the very file and bytes snapshotted at approval)."""
	name = bound_file(doc, field)
	if (
		name
		and doc.docstatus != 0
		and (name != doc.get(f"{field}_id") or fingerprint(name) != doc.get(f"{field}_sha256"))
	):
		name = None
	content = name and decrypt_bound(name, doc.name, field)
	if not content:
		raise QPFileError(_("The paper file is not a sealed file of this paper."))
	return content


# ---- watermark ----------------------------------------------------------------------------


def watermark(content, text):
	"""Stamp `text` at the foot and head of every page of the PDF `content`."""
	reader, writer = PdfReader(io.BytesIO(content)), PdfWriter()
	for page in reader.pages:
		page.merge_page(stamp(float(page.mediabox.width), float(page.mediabox.height), text))
		writer.add_page(page)
	out = io.BytesIO()
	writer.write(out)
	return out.getvalue()


def stamp(width, height, text):
	stamp_writer = PdfWriter()
	page = stamp_writer.add_blank_page(width, height)
	font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
		NameObject("/BaseFont"): NameObject("/Helvetica")})  # fmt: skip
	page[NameObject("/Resources")] = DictionaryObject(
		{NameObject("/Font"): DictionaryObject({NameObject("/FWm"): stamp_writer._add_object(font)})}
	)
	literal = pdf_literal(text)
	stream = DecodedStreamObject()
	stream.set_data(
		f"q 0.45 g BT /FWm 8 Tf 24 14 Td ({literal}) Tj ET BT /FWm 8 Tf 24 {height - 20:.0f} Td ({literal}) Tj ET Q".encode(
			"latin-1"
		)
	)
	page[NameObject("/Contents")] = stamp_writer._add_object(stream)
	return page


def pdf_literal(text):
	safe = text.encode("latin-1", "replace").decode("latin-1")
	return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
