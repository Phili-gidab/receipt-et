"""Merchant (tenant) onboarding + lookup.

A merchant carries its own fiscal identity (TIN, system type/number, seller
details, tax code) and credential REFERENCES (resolved at call time via the
secrets backend — never plaintext in the DB). Onboarding a merchant is how the
aggregator brings a new taxpayer onto the platform.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Merchant, MerchantSecret
from app.schemas import MerchantCreate, MerchantResponse

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.post("", response_model=MerchantResponse, status_code=201)
def create_merchant(payload: MerchantCreate, session: Session = Depends(get_session)) -> Merchant:
    """Onboard a new tenant. The optional ``secret`` block stores credential
    *references* (env names / file paths / Secrets Manager ids), never values."""
    exists = session.execute(
        select(Merchant).where(Merchant.tin == payload.tin)
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"Merchant with TIN {payload.tin} already exists.")

    merchant = Merchant(**payload.model_dump(exclude={"secret"}))
    if payload.secret is not None:
        merchant.secret = MerchantSecret(**payload.secret.model_dump())

    session.add(merchant)
    session.commit()
    session.refresh(merchant)
    return merchant


@router.get("", response_model=list[MerchantResponse])
def list_merchants(session: Session = Depends(get_session)) -> list[Merchant]:
    """List all tenants (no secrets returned)."""
    return list(session.execute(select(Merchant).order_by(Merchant.id)).scalars())


@router.get("/{tin}", response_model=MerchantResponse)
def get_merchant(tin: str, session: Session = Depends(get_session)) -> Merchant:
    """Fetch one tenant by TIN."""
    merchant = session.execute(
        select(Merchant).where(Merchant.tin == tin)
    ).scalar_one_or_none()
    if merchant is None:
        raise HTTPException(status_code=404, detail=f"No merchant with TIN {tin}.")
    return merchant
