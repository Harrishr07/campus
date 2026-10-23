"""M08-12 Crossref metadata for a DOI: one HTTPS request to the public Crossref works API and a pure parser of its answer.

Only the DOI's own text goes into the URL (quoted), the host is fixed, so nothing a user types can redirect the request."""

import re
from urllib.parse import quote

import frappe
import requests
from frappe import _

API = "https://api.crossref.org/works/"
TIMEOUT_SECONDS = 10
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?(?:doi\.org/|doi:)", re.IGNORECASE)
TYPES = {  # Crossref work type -> Publication Type
	"journal-article": "Journal Article",
	"proceedings-article": "Conference Paper",
	"book": "Book",
	"edited-book": "Book",
	"monograph": "Book",
	"book-chapter": "Book Chapter",
}


def normalise_doi(value):
	"""The DOI as lower-case `10.xxxx/suffix` (DOIs are case-insensitive), or throw when it is not one."""
	doi = DOI_PREFIX.sub("", (value or "").strip()).strip().lower()
	if not DOI_PATTERN.match(doi):
		frappe.throw(_("{0} is not a valid DOI. It looks like 10.1234/abc.").format(value))
	return doi


def fetch_work(doi):
	"""The Crossref `message` of `doi`; throws a plain message when Crossref doesn't know it or can't be reached."""
	doi = normalise_doi(doi)
	try:
		response = requests.get(API + quote(doi, safe=""), headers={"User-Agent": "OneBookCampus/1.0"}, timeout=TIMEOUT_SECONDS, allow_redirects=False)
	except requests.RequestException:
		frappe.throw(_("Crossref could not be reached. Enter the details by hand or try again later."))
	if response.status_code == 404:
		frappe.throw(_("Crossref has no record of the DOI {0}.").format(doi))
	if response.status_code != 200:  # a redirect (3xx) is not followed and lands here
		frappe.throw(_("Crossref could not give the details of {0} (HTTP {1}).").format(doi, response.status_code))
	try:
		return response.json().get("message") or {}
	except (ValueError, AttributeError):
		frappe.throw(_("Crossref gave an answer for {0} that could not be read. Enter the details by hand.").format(doi))


def parse_work(message):
	"""Publication fields from a Crossref work: title, container (journal / proceedings / book), ISSNs, date, authors, type, citations."""
	return {
		"title": first(message.get("title")),
		"container_title": first(message.get("container-title")),
		"publisher": message.get("publisher"),
		"issns": [issn.upper() for issn in message.get("ISSN") or []],
		"publication_date": work_date(message),
		"publication_type": TYPES.get(message.get("type")),
		"citations": message.get("is-referenced-by-count"),
		"authors": [author_of(a) for a in message.get("author") or [] if author_name(a)],
	}


def first(values):
	return (values or [None])[0]


def work_date(message):
	"""ISO date of the first of issued / published-print / published-online with a year; a missing month or day is 1."""
	for key in ("issued", "published-print", "published-online"):
		parts = ((message.get(key) or {}).get("date-parts") or [[]])[0]
		if parts and parts[0]:
			year, month, day = (list(parts) + [1, 1])[:3]
			return f"{int(year):04d}-{int(month or 1):02d}-{int(day or 1):02d}"


def author_name(author):
	return " ".join(filter(None, [author.get("given"), author.get("family")])) or author.get("name")


def author_of(author):
	affiliation = first([a.get("name") for a in author.get("affiliation") or [] if a.get("name")])
	return {"author_type": "External", "author_name": author_name(author), "affiliation": affiliation}
