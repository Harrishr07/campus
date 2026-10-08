"""M06-03 Question paper files: the attached PDFs are encrypted at rest and only decrypted (and watermarked) by the
download endpoint inside the release window.

Frappe serves /private/files/ through the File controller's own permission check, which grants the uploader and
Administrator regardless of app hooks, so access control alone cannot keep a paper closed. On save, a plain PDF in
an Attach field is replaced by a private `.enc` File holding its Fernet ciphertext (site encryption key) and the
plain File is deleted; a direct file URL then only ever returns ciphertext.
"""

import io

import frappe
from cryptography.fernet import Fernet
from frappe import _
from frappe.utils.password import get_encryption_key
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

SEALED_SUFFIX = ".enc"
PAPER_FILE_FIELDS = {"A": "set_a_file", "B": "set_b_file"}


def cipher():
	return Fernet(get_encryption_key().encode())


def seal_attachments(doc):
	"""Encrypt every newly attached paper of the Question Paper `doc` (validate)."""
	for field in PAPER_FILE_FIELDS.values():
		url = doc.get(field)
		if url and not url.endswith(SEALED_SUFFIX):
			doc.set(field, seal(doc, field, url))


def seal(doc, field, url):
	plain = [f.name for f in frappe.get_all("File", {"file_url": url}, ["name", "attached_to_doctype", "attached_to_name"])
		if not f.attached_to_doctype or (f.attached_to_doctype, f.attached_to_name) == (doc.doctype, doc.name)]  # fmt: skip
	if not plain:
		frappe.throw(_("The attached file {0} was not found.").format(url))
	content = frappe.get_doc("File", plain[0]).get_content(encodings=[])
	if not isinstance(content, bytes) or not content.startswith(b"%PDF"):
		frappe.throw(_("Attach the question paper as a PDF."))
	sealed = frappe.get_doc(
		{
			"doctype": "File", "file_name": f"{doc.name}-{field}.pdf{SEALED_SUFFIX}", "is_private": 1,
			"content": cipher().encrypt(content), "attached_to_doctype": doc.doctype, "attached_to_name": doc.name,
			"attached_to_field": field,
		}
	).insert(ignore_permissions=True)  # fmt: skip
	for name in plain:
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
	return sealed.file_url


def read_sealed(url):
	"""The decrypted PDF bytes behind a sealed file URL."""
	name = frappe.db.get_value("File", {"file_url": url})
	return cipher().decrypt(frappe.get_doc("File", name).get_content(encodings=[]))


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
		f"q 0.45 g BT /FWm 8 Tf 24 14 Td ({literal}) Tj ET BT /FWm 8 Tf 24 {height - 20:.0f} Td ({literal}) Tj ET Q".encode("latin-1")
	)
	page[NameObject("/Contents")] = stamp_writer._add_object(stream)
	return page


def pdf_literal(text):
	safe = text.encode("latin-1", "replace").decode("latin-1")
	return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
