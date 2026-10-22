"""M12-01 Lab equipment: the Assets whose Location is a laboratory's Asset Location and in the lab's college."""

import frappe
from frappe.query_builder import DocType


def lab_equipment(companies=None, laboratory=None):
	"""Equipment of the laboratories (all, of `companies`, or one), by lab then asset. `companies` None = all, [] = none."""
	if companies is not None and not companies:
		return []
	asset, lab = DocType("Asset"), DocType("Laboratory")
	query = (
		frappe.qb.from_(asset)
		.join(lab).on((lab.asset_location == asset.location) & (lab.company == asset.company))
		.select(
			lab.name.as_("laboratory"), lab.company, asset.name.as_("asset"), asset.asset_name, asset.asset_category,
			asset.purchase_date, asset.net_purchase_amount, asset.status,
		)
		.where(asset.docstatus < 2)
		.orderby(lab.name)
		.orderby(asset.name)
	)  # fmt: skip
	if companies is not None:
		query = query.where(lab.company.isin(companies))
	if laboratory:
		query = query.where(lab.name == laboratory)
	return query.run(as_dict=True)
