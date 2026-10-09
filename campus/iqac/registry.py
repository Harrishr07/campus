"""M01-02 Data point registry: `@campus_metric("key")` registers a function that returns {value, records}.

A data point function takes (company, period, department=None) (period is the academic year) and returns {"value": number, "records": [{"doctype", "name"}]}.
The registry is the only namespace a Framework Node formula may use.
"""

REGISTRY = {}
DESCRIPTIONS = {}  # key -> {"module", "description"}: what the Data Point DocType shows (synced from here)


def campus_metric(key, module=None, description=None):
	"""Register the decorated function as the data point `key`; `module` (Module Def) and `description` document it."""

	def register(function):
		if key in REGISTRY:
			raise ValueError(f"Data point {key} is already registered")
		REGISTRY[key] = function
		DESCRIPTIONS[key] = {"module": module, "description": description}
		return function

	return register


def data_point_keys():
	from campus.iqac import datapoints  # noqa: F401  (importing registers the data points)

	return set(REGISTRY)


def data_point(key, company, academic_year, department=None):
	"""Evaluate one registered data point: {"value", "records"}."""
	data_point_keys()
	return REGISTRY[key](company, academic_year, department)
