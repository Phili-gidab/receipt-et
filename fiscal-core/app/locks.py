"""Per-merchant chain serialization via a Postgres advisory lock (spec §6).

Each merchant's invoice chain (counter + last_irn) must be advanced by exactly
one writer at a time, even across concurrent requests / workers / boxes. Delta
(single-tenant MariaDB) used ``GET_LOCK``; the Postgres analogue is a
**transaction-scoped advisory lock** taken on the merchant's TIN:

    pg_advisory_xact_lock(hashtext('receipt_register:' || tin))

The lock is acquired inside the CURRENT transaction and released automatically
at COMMIT / ROLLBACK (that is what the ``_xact_`` variant guarantees), so it
cannot leak if the request crashes. This module wraps :func:`app.db
.pg_advisory_xact_lock` in a context manager keyed by merchant TIN.

Usage::

    with merchant_chain_lock(session, merchant.tin):
        # read InvoiceChain head, build, register, advance — all serialized.
        ...
    # lock released when the surrounding transaction commits/rolls back.

NOTE (transaction scope): because the lock is bound to the transaction, the
caller must keep the same transaction open from acquire through the chain write
(do NOT commit in the middle of the locked region, or the lock releases early).
The registration service commits exactly once, at the end of the locked block.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.db import pg_advisory_xact_lock

__all__ = ["LOCK_KEY_PREFIX", "lock_key_for_tin", "merchant_chain_lock"]

# Matches the spec §6 form: pg_advisory_xact_lock(hashtext('receipt_register:'||tin)).
LOCK_KEY_PREFIX = "receipt_register:"


def lock_key_for_tin(tin: str) -> str:
    """Return the stable advisory-lock key string for a merchant ``tin``."""
    return f"{LOCK_KEY_PREFIX}{tin}"


@contextmanager
def merchant_chain_lock(session: Session, tin: str) -> Iterator[None]:
    """Hold the per-merchant chain advisory lock for the current transaction.

    Acquires ``pg_advisory_xact_lock(hashtext('receipt_register:'||tin))`` on
    ``session``'s current transaction, blocking until granted. The lock is
    released by Postgres when that transaction ends (COMMIT/ROLLBACK), so this
    context manager does NOT itself release it — it only serializes the body.

    Args:
        session: the SQLAlchemy session whose transaction will hold the lock.
        tin: the merchant TIN to key the lock on.

    Yields:
        None. Run the chain read/build/register/advance inside the ``with``.
    """
    if not tin:
        raise ValueError("merchant_chain_lock requires a non-empty merchant TIN.")
    pg_advisory_xact_lock(session, lock_key_for_tin(tin))
    yield
