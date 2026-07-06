"""Receipt fiscal-core — multi-tenant MoR EIMS fiscalization service.

See docs/MOR_EIMS_CONTRACT.md (repo root) for the authoritative request
contract. All fiscal values are per-merchant state in the database; crypto and
request builders are PURE functions that take the merchant's key/cert as
arguments and never read global config.
"""

__version__ = "0.1.0"
