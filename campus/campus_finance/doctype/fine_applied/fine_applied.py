"""M09-01 Fine Applied: the unique (invoice, slab) record that makes the daily fine run idempotent.

The document name is the key, so the primary key is the database-level uniqueness guarantee.
"""

from frappe.model.document import Document


class FineApplied(Document):
	def autoname(self):
		self.name = key(self.sales_invoice, self.slab_key)


def key(sales_invoice, slab_key):
	return f"{sales_invoice}::{slab_key}"
