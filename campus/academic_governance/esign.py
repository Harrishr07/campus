"""M02-03 E-sign adapter interface for minutes and resolutions. No provider ships in Phase 2: a provider (Phase 5)
subclasses ESignProvider and registers itself; callers ask get_provider() and get a clear error until then."""

from abc import ABC, abstractmethod

import frappe
from frappe import _

_providers = {}


class ESignProvider(ABC):
	@abstractmethod
	def request_signature(self, doctype, name, signers):
		"""Ask the signers (list of Users) to sign the document; returns the provider's reference."""

	@abstractmethod
	def status(self, reference):
		"""Pending, Signed or Declined for a reference returned by request_signature."""


def register_provider(name, provider):
	_providers[name] = provider


def get_provider(name=None):
	if not _providers:
		frappe.throw(_("No e-sign provider is configured"))
	return _providers[name] if name else next(iter(_providers.values()))
