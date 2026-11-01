"""Accounts: the banks and wallets to read, their statement settings, and importing history
that isn't in Gmail (the foodpanda account, CSV files)."""

import io
import json
from dataclasses import replace

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from order_tracker.foodpanda_account import COUNTRIES as FOODPANDA_COUNTRIES
from order_tracker.foodpanda_account import (
    FoodpandaAPIError, FoodpandaAuthError, fetch_order_history, orders_from_history,
)
from order_tracker.importers import guess_mapping, orders_from_csv
from order_tracker.institutions import (
    KINDS, PRESETS, STATEMENT_PREFIX, InstitutionSource, StatementSource, make_key, split_terms,
)
from order_tracker.models import Institution
from order_tracker.parsers import PROVIDERS
from order_tracker.reconcile import reconcile
from order_tracker.storage import OrderStore

from .common import user_store, viewer_tz

router = APIRouter(prefix="/api/accounts")

ADDED = "Added {}. Use Sync now on Home to read its emails."
MAX_CSV_BYTES = 5 * 1024 * 1024


def _terms(value: list[str] | str) -> list[str]:
    return split_terms(value) if isinstance(value, str) else [t.strip() for t in value if t.strip()]


def _institution(i: Institution) -> dict:
    return {
        "key": i.key, "name": i.name, "kind": i.kind, "kind_label": KINDS.get(i.kind, i.kind.title()),
        "enabled": i.enabled, "senders": ", ".join(i.sender_terms), "subjects": ", ".join(i.subject_terms),
        "currency": i.currency, "statements": i.statements,
        "alerts_query": InstitutionSource(i).gmail_query,
        "statements_query": StatementSource(i).gmail_query if i.statements else None,
    }


# --- banks and wallets ---

@router.get("/institutions")
def institutions(store: OrderStore = Depends(user_store)) -> dict:
    tracked = store.institutions()
    keys = {i.key for i in tracked}
    return {
        "tracked": [_institution(i) for i in tracked],
        "presets": [{"key": p.key, "name": p.name, "kind": p.kind, "kind_label": KINDS[p.kind]}
                    for p in PRESETS if p.key not in keys],
        "kinds": [{"key": k, "label": v} for k, v in KINDS.items()],
    }


class NewInstitution(BaseModel):
    preset: str | None = None   # a key from the presets; or the fields below for your own
    name: str = ""
    kind: str = "bank"
    senders: list[str] | str = []
    subjects: list[str] | str = []
    currency: str = "PKR"


@router.post("/institutions")
def add_institution(body: NewInstitution, store: OrderStore = Depends(user_store)) -> dict:
    taken = {i.key for i in store.institutions()}
    if body.preset:
        preset = next((p for p in PRESETS if p.key == body.preset), None)
        if preset is None:
            raise HTTPException(404, "That bank or wallet isn't in the list.")
        if preset.key in taken:
            raise HTTPException(409, f"{preset.name} is already added.")
        store.save_institution(preset)
        return {"message": ADDED.format(preset.name), "key": preset.key}
    senders = _terms(body.senders)
    if not body.name.strip() or not senders:
        raise HTTPException(400, "Enter a name and at least one sender.")
    institution = Institution(
        key=make_key(body.name, taken | {p.key for p in PRESETS}), name=body.name.strip(),
        kind=body.kind if body.kind in KINDS else "bank", sender_terms=senders,
        subject_terms=_terms(body.subjects), currency=body.currency.strip().upper() or "PKR",
    )
    store.save_institution(institution)
    return {"message": ADDED.format(institution.name), "key": institution.key}


class InstitutionChange(BaseModel):
    name: str | None = None
    kind: str | None = None
    senders: list[str] | str | None = None
    subjects: list[str] | str | None = None
    currency: str | None = None
    enabled: bool | None = None


def _find(store: OrderStore, key: str) -> Institution:
    found = next((i for i in store.institutions() if i.key == key), None)
    if found is None:
        raise HTTPException(404, "That bank or wallet isn't there any more.")
    return found


@router.patch("/institutions/{key}")
def change_institution(key: str, body: InstitutionChange, store: OrderStore = Depends(user_store)) -> dict:
    current = _find(store, key)
    changes = {}
    if body.name is not None and body.name.strip():
        changes["name"] = body.name.strip()
    if body.kind in KINDS:
        changes["kind"] = body.kind
    if body.senders is not None:
        senders = _terms(body.senders)
        if not senders:
            raise HTTPException(400, "Keep at least one sender.")
        changes["sender_terms"] = senders
    if body.subjects is not None:
        changes["subject_terms"] = _terms(body.subjects)
    if body.currency is not None and body.currency.strip():
        changes["currency"] = body.currency.strip().upper()
    if body.enabled is not None:
        changes["enabled"] = body.enabled
    store.save_institution(replace(current, **changes))  # keeps the statement settings
    reconcile(store)
    message = "Saved."
    if "sender_terms" in changes or "subject_terms" in changes:
        message += " Re-scan it from Sync options on Home to read its emails again."
    return {"message": message}


@router.delete("/institutions/{key}")
def remove_institution(key: str, store: OrderStore = Depends(user_store)) -> dict:
    """Remove a bank or wallet, and everything read from its emails."""
    institution = _find(store, key)
    store.delete_institution(key)
    reconcile(store)
    return {"message": f"Removed {institution.name} and what was read from its emails."}


# --- statement settings ---

@router.get("/statements")
def statement_settings(store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    tracked = store.institutions()
    names = {i.key: i.name for i in tracked}
    unread = store.skipped_frame()
    unread = unread[unread["provider"].str.startswith(STATEMENT_PREFIX)]
    read = store.statements_frame()
    return {
        "empty": not tracked,
        "unread": [{
            "received": f"{r.received_at.tz_convert(tz):%d %b %Y}",
            "bank": names.get(r.provider.removeprefix(STATEMENT_PREFIX), r.provider.removeprefix(STATEMENT_PREFIX)),
            "subject": r.subject, "reason": r.reason,
        } for r in unread.itertuples()],
        "settings": [{
            "key": i.key, "name": i.name, "statements": i.statements, "has_password": bool(i.statement_password),
            "senders": ", ".join(i.statement_senders), "subjects": ", ".join(i.statement_subjects),
            "senders_placeholder": ", ".join(i.sender_terms), "query": StatementSource(i).gmail_query,
        } for i in tracked],
        "read": [{
            "bank": names.get(r.institution, r.institution),
            "period": " – ".join(f"{d:%d %b %Y}" for d in (r.period_start, r.period_end) if pd.notna(d)) or "–",
            "received": f"{r.received_at.tz_convert(tz):%d %b %Y}", "files": r.files,
            "found": int(r.rows_found), "added": int(r.rows_added),
        } for r in read.itertuples()],
    }


class StatementChange(BaseModel):
    statements: bool
    password: str = ""          # empty keeps the saved one
    remove_password: bool = False
    senders: list[str] | str = []
    subjects: list[str] | str = []


@router.put("/institutions/{key}/statements")
def change_statement_settings(key: str, body: StatementChange, store: OrderStore = Depends(user_store)) -> dict:
    institution = _find(store, key)
    password = "" if body.remove_password else (body.password or institution.statement_password)
    store.save_institution(replace(
        institution, statements=body.statements, statement_password=password,
        statement_senders=_terms(body.senders), statement_subjects=_terms(body.subjects),
    ))
    # Statements that couldn't be opened or found get another try.
    store.retry_unread_statements(key)
    message = f"Saved the statement settings for {institution.name}."
    if body.password:
        message += " Statements that couldn't be opened are tried again on the next sync."
    return {"message": message}


# --- imports ---

class FoodpandaImport(BaseModel):
    token: str
    country: str = "PK"


@router.get("/import/options")
def import_options() -> dict:
    return {
        "countries": [{"key": k, "name": v["name"]} for k, v in FOODPANDA_COUNTRIES.items()],
        "services": [{"key": k, "name": p.name} for k, p in PROVIDERS.items()],
    }


@router.post("/import/foodpanda")
def import_foodpanda(body: FoodpandaImport, store: OrderStore = Depends(user_store)) -> dict:
    """Your full foodpanda history, with the login token. The token is used once and not saved."""
    if not body.token.strip():
        raise HTTPException(400, "Paste your token first.")
    if body.country not in FOODPANDA_COUNTRIES:
        raise HTTPException(400, "Pick a country.")
    try:
        items = fetch_order_history(body.token, body.country)
    except (FoodpandaAuthError, FoodpandaAPIError) as exc:
        raise HTTPException(502, str(exc)) from exc
    parsed, unusable = orders_from_history(items, body.country)
    added = sum(store.add_order(order) for order in parsed)
    reconcile(store)
    result = f"Found {len(items)} orders: {added} new, {len(parsed) - added} already tracked"
    if unusable:
        result += f", {unusable} declined or unreadable"
    return {"message": result + "."}


async def _read_csv(file: UploadFile) -> pd.DataFrame:
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(413, "That file is too big (5 MB at most).")
    try:
        frame = pd.read_csv(io.BytesIO(data))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"Couldn't read that file: {exc}") from exc
    frame.columns = [str(c) for c in frame.columns]
    return frame


@router.post("/import/csv/preview")
async def preview_csv(file: UploadFile = File(...)) -> dict:
    """The file's columns, its first rows, which column is which (a guess), and the service."""
    frame = await _read_csv(file)
    name = (file.filename or "").lower().replace(" ", "")
    service = next((k for k in PROVIDERS if k in name), next(iter(PROVIDERS)))
    return {
        "columns": list(frame.columns),
        "preview": json.loads(frame.head(5).to_json(orient="records", date_format="iso")),
        "mapping": guess_mapping(list(frame.columns)),
        "service": service,
    }


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), service: str = Form(...), mapping: str = Form(...),
                     currency: str = Form("PKR"), dayfirst: bool = Form(True), dry_run: bool = Form(False),
                     store: OrderStore = Depends(user_store)) -> dict:
    """Import orders from the file. With dry_run, only say how many rows can be read."""
    if service not in PROVIDERS:
        raise HTTPException(400, "Pick the service the file is from.")
    frame = await _read_csv(file)
    try:
        chosen = {k: (v or None) for k, v in json.loads(mapping).items()}
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "The column choices weren't readable.") from exc
    fields = {"date", "amount", "merchant", "reference", "currency"}
    chosen = {f: chosen.get(f) if chosen.get(f) in frame.columns else None for f in fields}
    if not chosen["date"] or not chosen["amount"]:
        raise HTTPException(400, "Pick the date and amount columns to continue.")
    parsed, bad_rows = orders_from_csv(frame, service, chosen, currency.strip().upper() or "PKR", dayfirst)
    summary = f"{len(parsed)} order(s) ready to import."
    if bad_rows:
        summary += f" {bad_rows} row(s) will be skipped (no readable date or amount)."
    if dry_run:
        return {"message": summary, "ready": len(parsed), "bad_rows": bad_rows}
    added = sum(store.add_order(order, "csv") for order in parsed)
    reconcile(store)
    return {"message": f"Imported {added} new order(s); {len(parsed) - added} were already there.",
            "added": added}
