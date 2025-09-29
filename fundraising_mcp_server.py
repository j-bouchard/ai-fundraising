#!/usr/bin/env python3
"""
AI Fundraising MCP Server (Salesforce/NPSP)
- Async stdio MCP server exposing fundraising analytics and Salesforce write tools
- OAuth 2.0 refresh-token flow to get session for simple-salesforce
- NLP-to-SOQL parsing for donor segments

This is an MVP intended for demos while following production-grade patterns.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from cachetools import TTLCache
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from pathlib import Path

# Optional imports guarded for environments without these deps during tests
MCP_AVAILABLE = False
FASTMCP_AVAILABLE = False
try:
    from mcp.server.stdio import stdio_server
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
    try:
        from mcp.server.fastmcp import FastMCP  # preferred high-level API
        FASTMCP_AVAILABLE = True
    except Exception:
        FASTMCP_AVAILABLE = False
except Exception:  # pragma: no cover - allow tests without mcp installed
    Server = object  # type: ignore
    Tool = object  # type: ignore
    TextContent = dict  # type: ignore
    stdio_server = None  # type: ignore

try:
    from simple_salesforce import Salesforce, SalesforceMalformedRequest
except Exception:  # pragma: no cover
    Salesforce = object  # type: ignore
    class SalesforceMalformedRequest(Exception):
        pass

import requests

# ------------------------------------------------------------
# Logging & Env
# ------------------------------------------------------------
# Always load .env from the project directory (next to this file), regardless of CWD
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fundraising_mcp")

DEFAULT_LIMIT = 25
CACHE_TTL_SECONDS = 60

# ------------------------------------------------------------
# Utilities: formatting, parsing
# ------------------------------------------------------------

def fmt_currency(amount: Optional[float | int | Decimal]) -> str:
    if amount is None:
        return "$0.00"
    return f"${float(amount):,.2f}"


def fmt_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def header(title: str) -> str:
    return f"{title}\n" + "-" * max(6, len(title))


@dataclass
class Timeframe:
    start: datetime
    end: datetime


AMOUNT_PATTERN = re.compile(r"\$?\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?|\d+\s*[kKmMbB])")
MONTHS_PATTERN = re.compile(r"(last|past)\s*(\d+)\s*(month|months)", re.I)
YEARS_PATTERN = re.compile(r"(last|past)\s*(\d+)\s*(year|years)", re.I)
SIX_MONTHS_PATTERN = re.compile(r"(last|past)\s*6\s*months", re.I)
ONE_YEAR_PATTERN = re.compile(r"(last|past)\s*1\s*year", re.I)


def parse_amount(text: str) -> Optional[float]:
    match = AMOUNT_PATTERN.search(text.replace(",", ""))
    if not match:
        return None
    raw = match.group(1).strip().lower()
    factor = 1
    if raw.endswith("k"):
        factor = 1_000
        raw = raw[:-1]
    elif raw.endswith("m"):
        factor = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("b"):
        factor = 1_000_000_000
        raw = raw[:-1]
    try:
        return float(raw) * factor
    except Exception:
        return None


def parse_timeframe(text: str) -> Optional[Timeframe]:
    now = datetime.now(timezone.utc)
    # Specific helpers
    m = MONTHS_PATTERN.search(text)
    if m:
        months = int(m.group(2))
        return Timeframe(start=now - relativedelta(months=months), end=now)
    m = YEARS_PATTERN.search(text)
    if m:
        years = int(m.group(2))
        return Timeframe(start=now - relativedelta(years=years), end=now)
    if SIX_MONTHS_PATTERN.search(text):
        return Timeframe(start=now - relativedelta(months=6), end=now)
    if ONE_YEAR_PATTERN.search(text):
        return Timeframe(start=now - relativedelta(years=1), end=now)
    # Defaults
    return None


# ------------------------------------------------------------
# Salesforce OAuth helper
# ------------------------------------------------------------
class SalesforceAuthError(Exception):
    pass


class SalesforceClient:
    """Thin async wrapper around simple_salesforce with OAuth refresh token flow.

    All network calls are delegated to a thread via asyncio.to_thread for async compatibility.
    """

    def __init__(self) -> None:
        self.client_id = os.getenv("SF_CLIENT_ID")
        self.client_secret = os.getenv("SF_CLIENT_SECRET")
        self.refresh_token = os.getenv("SF_REFRESH_TOKEN")
        self.instance_url = os.getenv("SF_INSTANCE_URL")
        self.domain = os.getenv("SF_DOMAIN", "login")

        self.username = os.getenv("SF_USERNAME")
        self.password = os.getenv("SF_PASSWORD")
        self.security_token = os.getenv("SF_SECURITY_TOKEN")

        self._sf: Optional[Salesforce] = None
        self._access_token: Optional[str] = None

    def _token_endpoint(self) -> str:
        base = "https://login.salesforce.com" if self.domain == "login" else "https://test.salesforce.com"
        return f"{base}/services/oauth2/token"

    def _refresh_access_token(self) -> Tuple[str, str]:
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise SalesforceAuthError("Missing OAuth env vars: SF_CLIENT_ID/SF_CLIENT_SECRET/SF_REFRESH_TOKEN")
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        resp = requests.post(self._token_endpoint(), data=data, timeout=30)
        if resp.status_code != 200:
            raise SalesforceAuthError(f"OAuth refresh failed: {resp.status_code} {resp.text}")
        tok = resp.json()
        access_token = tok.get("access_token")
        instance_url = tok.get("instance_url", self.instance_url)
        if not (access_token and instance_url):
            raise SalesforceAuthError("OAuth refresh succeeded but missing access_token/instance_url")
        return access_token, instance_url

    async def connect(self) -> None:
        def _connect_sync() -> Salesforce:
            # Prefer OAuth refresh token
            try:
                access_token, inst_url = self._refresh_access_token()
                sf = Salesforce(instance_url=inst_url, session_id=access_token)
                self._access_token = access_token
                return sf
            except Exception as e:
                logger.warning("OAuth refresh failed, attempting username/password if provided: %s", e)
                if not (self.username and self.password and self.security_token):
                    raise
                # Fallback: username/password
                return Salesforce(
                    username=self.username,
                    password=self.password,
                    security_token=self.security_token,
                    domain=self.domain,
                )

        self._sf = await asyncio.to_thread(_connect_sync)
        logger.info("Connected to Salesforce")

    async def soql(self, query: str) -> Dict[str, Any]:
        async def _query_sync() -> Dict[str, Any]:
            assert self._sf is not None
            return self._sf.query(query)  # type: ignore[attr-defined]
        try:
            return await asyncio.to_thread(lambda: self._sf.query(query))  # type: ignore
        except SalesforceMalformedRequest as e:  # type: ignore
            raise
        except Exception as e:
            raise

    async def create(self, sobject: str, data: Dict[str, Any]) -> Dict[str, Any]:
        def _create_sync() -> Dict[str, Any]:
            assert self._sf is not None
            sobj = getattr(self._sf, sobject)  # type: ignore[attr-defined]
            return sobj.create(data)  # type: ignore
        return await asyncio.to_thread(_create_sync)

    async def update(self, sobject: str, record_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        def _update_sync() -> Dict[str, Any]:
            assert self._sf is not None
            sobj = getattr(self._sf, sobject)  # type: ignore[attr-defined]
            return sobj.update(record_id, data)  # type: ignore
        return await asyncio.to_thread(_update_sync)


# ------------------------------------------------------------
# NLP to SOQL generation for donor criteria
# ------------------------------------------------------------
class SOQLBuilder:
    @staticmethod
    def lapsed_donors(months: int = 12, limit: int = DEFAULT_LIMIT) -> str:
        # Donors with gifts > 12 months ago but none in last 12 months
        return (
            "SELECT Id, Name, Email, "
            "(SELECT SUM(Amount) total FROM Opportunities WHERE IsWon=true) LifetimeGiving, "
            "(SELECT MAX(CloseDate) lastGiftDate FROM Opportunities WHERE IsWon=true) LastGiftDate "
            "FROM Contact "
            "WHERE Id IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true) "
            f"AND Id NOT IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true AND Opportunity.CloseDate = LAST_N_DAYS:{months*30}) "
            f"LIMIT {limit}"
        )

    @staticmethod
    def major_donors_over(amount: float, limit: int = DEFAULT_LIMIT) -> str:
        # Contacts whose lifetime giving exceeds amount
        return (
            "SELECT Id, Name, Email, "
            "(SELECT SUM(Amount) total FROM Opportunities WHERE IsWon=true) LifetimeGiving "
            "FROM Contact "
            "WHERE Id IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true) "
            f"AND Id IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true GROUP BY ContactId HAVING SUM(Opportunity.Amount) > {int(amount)}) "
            f"LIMIT {limit}"
        )

    @staticmethod
    def recent_donors_last_n_months(months: int, limit: int = DEFAULT_LIMIT) -> str:
        days = max(1, months * 30)
        return (
            "SELECT Id, Name, Email, "
            "(SELECT MAX(CloseDate) lastGiftDate FROM Opportunities WHERE IsWon=true AND CloseDate = LAST_N_DAYS:"
            f"{days}) LastGiftDate "
            "FROM Contact WHERE Id IN (SELECT ContactId FROM OpportunityContactRole WHERE "
            f"Opportunity.IsWon=true AND Opportunity.CloseDate = LAST_N_DAYS:{days}) "
            f"LIMIT {limit}"
        )

    @staticmethod
    def first_time_donors(limit: int = DEFAULT_LIMIT) -> str:
        # Contacts with exactly one won opportunity
        return (
            "SELECT Id, Name, Email FROM Contact WHERE "
            "Id IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true GROUP BY ContactId HAVING COUNT(Opportunity.Id) = 1) "
            f"LIMIT {limit}"
        )


def build_soql_from_criteria(criteria: str, limit: int = DEFAULT_LIMIT) -> Tuple[str, Dict[str, Any]]:
    """Return (soql, meta) based on simple NL parsing.

    Handles: lapsed donors, major donors over $X, recent donors last N months, first-time donors.
    """
    text = criteria.lower().strip()
    meta: Dict[str, Any] = {"limit": limit}

    if "lapsed" in text:
        months = 12
        tf = parse_timeframe(text)
        if tf:
            # approximate months from days delta
            months = max(1, int((datetime.now(timezone.utc) - tf.start).days / 30))
        meta.update({"segment": "lapsed_donors", "months": months})
        return SOQLBuilder.lapsed_donors(months=months, limit=limit), meta

    if "major" in text or "over" in text or "$" in text:
        amt = parse_amount(text) or 1000.0
        meta.update({"segment": "major_donors_over", "amount": amt})
        return SOQLBuilder.major_donors_over(amount=amt, limit=limit), meta

    if "recent" in text and "month" in text:
        months = 6
        tf = parse_timeframe(text)
        if tf:
            months = max(1, int((datetime.now(timezone.utc) - tf.start).days / 30))
        meta.update({"segment": "recent_donors", "months": months})
        return SOQLBuilder.recent_donors_last_n_months(months=months, limit=limit), meta

    if "first" in text or "first-time" in text:
        meta.update({"segment": "first_time_donors"})
        return SOQLBuilder.first_time_donors(limit=limit), meta

    # Default: recent donors 6 months
    months = 6
    meta.update({"segment": "recent_donors", "months": months, "defaulted": True})
    return SOQLBuilder.recent_donors_last_n_months(months=months, limit=limit), meta


# ------------------------------------------------------------
# NL → SOQL (general router)
# ------------------------------------------------------------
def nl_to_soql(question: str, default_limit: int = DEFAULT_LIMIT) -> Tuple[str, str]:
    """Very small heuristic router for common fundraising questions.

    Returns (soql, explanation).
    """
    q = question.lower().strip()

    # How many donations have we had this month?
    if re.search(r"how\s+many\s+(donation|gift)s?.*this\s+month", q):
        soql = "SELECT COUNT() FROM Opportunity WHERE IsWon = true AND CloseDate = THIS_MONTH"
        return soql, "Count of won opportunities in the current month"

    # Who are our top donors this quarter? (top N by sum)
    m = re.search(r"top\s+(\d+)\s+donor", q)
    top_n = int(m.group(1)) if m else 10
    if "top" in q and "donor" in q and ("quarter" in q or "this quarter" in q):
        # Aggregate by Contact via OpportunityContactRole
        soql = (
            "SELECT ContactId, SUM(Opportunity.Amount) total "
            "FROM OpportunityContactRole "
            "WHERE Opportunity.IsWon = true AND Opportunity.CloseDate = THIS_QUARTER "
            "GROUP BY ContactId ORDER BY SUM(Opportunity.Amount) DESC "
            f"LIMIT {top_n}"
        )
        return soql, "Top donors this quarter by total won amount"

    # Who gave last year but hasn't given since?
    if ("last year" in q or "this time last year" in q) and ("hasn't given since" in q or "not since" in q or "haven't given since" in q):
        soql = (
            "SELECT Id, Name, Email FROM Contact WHERE Id IN ("
            "SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true AND Opportunity.CloseDate = LAST_YEAR) "
            "AND Id NOT IN (SELECT ContactId FROM OpportunityContactRole WHERE Opportunity.IsWon=true AND Opportunity.CloseDate = THIS_YEAR) "
            f"LIMIT {default_limit}"
        )
        return soql, "Contacts who gave last year but not yet this year"

    # Recent donors N months
    m = re.search(r"last\s*(\d+)\s*months?", q)
    if ("donor" in q or "gift" in q) and m:
        months = max(1, int(m.group(1)))
        soql = SOQLBuilder.recent_donors_last_n_months(months=months, limit=default_limit)
        return soql, f"Contacts with gifts in the last {months} months"

    # Fallback: try a reasonable default segment
    soql = SOQLBuilder.recent_donors_last_n_months(months=6, limit=default_limit)
    return soql, "Fallback: recent donors in the last 6 months"

# ------------------------------------------------------------
# MCP Server and Tools
# ------------------------------------------------------------
class FundraisingServer:
    def __init__(self) -> None:
        self.server = Server("fundraising-mcp") if (MCP_AVAILABLE and not FASTMCP_AVAILABLE) else None
        self.fastmcp = FastMCP("fundraising-mcp") if FASTMCP_AVAILABLE else None
        self.sf = SalesforceClient()
        self.cache: TTLCache[str, Dict[str, Any]] = TTLCache(maxsize=128, ttl=CACHE_TTL_SECONDS)

    async def ensure_connected(self) -> None:
        try:
            # _sf is set after connect(); avoid re-connecting every call
            if getattr(self.sf, "_sf", None) is None:
                await self.sf.connect()
        except Exception as e:
            raise

    # ------------------------ Helper responses ------------------------
    def _format_records(self, title: str, records: List[Dict[str, Any]], insights: List[str], next_steps: List[str]) -> str:
        lines = [header(title)]
        for r in records:
            name = r.get("Name") or r.get("Contact", {}).get("Name") or "Unknown"
            email = r.get("Email") or ""
            total = r.get("LifetimeGiving") or r.get("total") or r.get("attributes", {}).get("total")
            last = r.get("LastGiftDate") or r.get("lastGiftDate")
            if isinstance(last, list) and last:
                last = last[0]
            lines.append(f"- Name: {name}")
            if email:
                lines.append(f"  - Email: {email}")
            if total:
                lines.append(f"  - Lifetime Giving: {fmt_currency(float(total) if not isinstance(total, (int, float)) else total)}")
            if last:
                if isinstance(last, str):
                    lines.append(f"  - Last Gift: {last}")
                else:
                    lines.append(f"  - Last Gift: {fmt_date(last)}")
        if insights:
            lines.append("")
            lines.append(header("AI Insights"))
            lines.extend([f"- {i}" for i in insights])
        if next_steps:
            lines.append("")
            lines.append(header("Next Steps"))
            lines.extend([f"- {n}" for n in next_steps])
        return "\n".join(lines)

    # ------------------------ Tool impls ------------------------
    async def tool_query_donors(self, criteria: str, limit: int = DEFAULT_LIMIT) -> str:
        await self.ensure_connected()
        soql, meta = build_soql_from_criteria(criteria, limit=limit)
        cache_key = json.dumps({"t": "q", "q": soql})
        if cache_key in self.cache:
            result = self.cache[cache_key]
        else:
            try:
                result = await self.sf.soql(soql)
            except SalesforceMalformedRequest as e:  # type: ignore
                return (header("SOQL Error") + f"\n- Query: `{soql}`\n- Message: {e}\n- Suggestion: Check field names and ensure NPSP is installed.")
            except Exception as e:
                return header("Salesforce Error") + f"\n- Unable to query donors. {e}"
            self.cache[cache_key] = result
        records = result.get("records", [])[:limit]
        insights = [
            f"Segment: {meta.get('segment')}",
            "Prioritize donors with higher lifetime giving and recent engagement.",
        ]
        steps = [
            "Create follow-up tasks for top 5 donors.",
            "Draft personalized outreach acknowledging specific past gifts.",
        ]
        return self._format_records("Donor Results", records, insights, steps)

    async def tool_run_soql(self, query: str, limit: int = DEFAULT_LIMIT) -> str:
        await self.ensure_connected()
        q = query.strip()
        try:
            res = await self.sf.soql(q)
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to run SOQL. {e}\n- Query: `{q}`"
        # Special-case COUNT()
        if res.get("records") == [] and "totalSize" in res and q.lower().startswith("select count"):
            return header("SOQL Count Result") + f"\n- Count: {res.get('totalSize', 0)}\n- Query: `{q}`"
        # Truncate for display
        records = res.get("records", [])[:limit]
        return header("SOQL Result") + f"\n- Records returned: {len(records)} of {res.get('totalSize', len(records))}\n- Query: `{q}`\n\n" + json.dumps(records, default=str, indent=2)

    async def tool_create_record(self, sobject: str, fields: Dict[str, Any]) -> str:
        """Generic creator for any sObject.

        Example calls:
        - sobject: "Contact", fields: {"FirstName":"Ada","LastName":"Lovelace","Email":"ada@example.org"}
        - sobject: "Task", fields: {"Subject":"Call donor","WhoId":"003...","ActivityDate":"2025-10-01"}
        - sobject: "Opportunity", fields: {"Name":"FY25 Gift","StageName":"Closed Won","CloseDate":"2025-10-01","Amount":5000}
        """
        await self.ensure_connected()
        if not sobject or not isinstance(fields, dict) or not fields:
            return header("Validation Error") + "\n- Provide sobject (string) and fields (non-empty object)."
        try:
            res = await self.sf.create(sobject, fields)
            return header("Record Created") + f"\n- sObject: {sobject}\n- Id: {res.get('id')}\n- Fields: {json.dumps(fields, default=str)}"
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to create {sobject}. {e}"

    async def tool_update_record(self, sobject: str, record_id: str, fields: Dict[str, Any]) -> str:
        """Generic updater for any sObject by Id.

        Example:
        - sobject: "Contact", record_id: "003...", fields: {"Email":"new@example.org"}
        - sobject: "Opportunity", record_id: "006...", fields: {"Amount": 7500}
        """
        await self.ensure_connected()
        if not sobject or not record_id or not isinstance(fields, dict) or not fields:
            return header("Validation Error") + "\n- Provide sobject, record_id, and fields (non-empty object)."
        try:
            await self.sf.update(sobject, record_id, fields)
            return header("Record Updated") + f"\n- sObject: {sobject}\n- Id: {record_id}\n- Fields: {json.dumps(fields, default=str)}"
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to update {sobject} {record_id}. {e}"

    async def tool_ask_salesforce(self, question: str, limit: int = DEFAULT_LIMIT) -> str:
        await self.ensure_connected()
        soql, why = nl_to_soql(question, default_limit=limit)
        try:
            res = await self.sf.soql(soql)
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to answer question. {e}\n- SOQL tried: `{soql}`"

        # COUNT() case
        if res.get("records") == [] and "totalSize" in res and soql.lower().startswith("select count"):
            return header("Answer") + f"\n- {why}\n- Count: {res.get('totalSize', 0)}\n- SOQL: `{soql}`"

        # Otherwise print top N records
        recs = res.get("records", [])[:limit]
        lines = [header("Answer"), f"- {why}", f"- Returned: {len(recs)} of {res.get('totalSize', len(recs))}", f"- SOQL: `{soql}`", "", header("Top Rows")]
        if not recs:
            lines.append("- No records matched.")
        else:
            # Print a compact subset of fields
            for r in recs:
                name = r.get("Name") or r.get("Contact", {}).get("Name") or r.get("ContactId") or r.get("Id")
                amt = r.get("Amount") or r.get("total") or r.get("expr0")
                d = r.get("CloseDate")
                parts = [f"- {name}"]
                if amt is not None:
                    try:
                        parts.append(f"| {fmt_currency(float(amt))}")
                    except Exception:
                        parts.append(f"| {amt}")
                if d:
                    parts.append(f"| {d}")
                lines.append(" ".join(parts))
        return "\n".join(lines)

    async def tool_get_donor_profile(self, identifier: str) -> str:
        await self.ensure_connected()
        # identifier can be Contact Id or Name
        if not identifier:
            return header("Validation Error") + "\n- identifier is required"
        # Build SOQL to fetch contact and summary of opportunities
        # Contact/Lead/Owner style prefix check; 003 is Contact prefix
        if re.match(r"^(003|005)[A-Za-z0-9]{12,18}$", identifier):
            where = f"Id = '{identifier}'"
        else:
            # Avoid complex nested quotes inside an f-string by pre-sanitizing
            safe = identifier.replace("'", "\\'")
            where = "Name LIKE '%" + safe + "%'"
        soql = (
            "SELECT Id, Name, Email, Phone, MailingCity, MailingState, "
            "(SELECT Amount, CloseDate, StageName FROM Opportunities WHERE IsWon=true ORDER BY CloseDate DESC LIMIT 5) RecentGifts, "
            "(SELECT SUM(Amount) total FROM Opportunities WHERE IsWon=true) LifetimeGiving "
            f"FROM Contact WHERE {where} LIMIT 1"
        )
        try:
            res = await self.sf.soql(soql)
        except Exception as e:
            msg = str(e)
            if "REQUEST_LIMIT_EXCEEDED" in msg or "REQUEST_LIMIT" in msg:
                return header("Salesforce Rate Limit") + "\n- You've hit the API limit. Try again later or reduce query size."
            return header("Salesforce Error") + f"\n- Unable to fetch donor profile. {e}"
        recs = res.get("records", [])
        if not recs:
            return header("Not Found") + f"\n- No contact matched '{identifier}'"
        c = recs[0]
        lines = [header(f"Donor Profile: {c.get('Name')}")]
        lines.append(f"- Email: {c.get('Email','')}")
        lines.append(f"- Phone: {c.get('Phone','')}")
        city = c.get('MailingCity') or ''
        state = c.get('MailingState') or ''
        if city or state:
            lines.append(f"- Location: {city}, {state}".strip(', '))
        lifetime = c.get('LifetimeGiving') or 0
        lines.append(f"- Lifetime Giving: {fmt_currency(float(lifetime) if lifetime else 0)}")
        # Recent gifts
        lines.append("")
        lines.append(header("Recent Gifts"))
        gifts = c.get('RecentGifts', []) or []
        if not gifts:
            lines.append("- None on record")
        else:
            for g in gifts:
                lines.append(f"- {fmt_date(datetime.fromisoformat(g.get('CloseDate')) if g.get('CloseDate') else None)} | {fmt_currency(g.get('Amount'))} | {g.get('StageName')}")
        # Insights
        insights = [
            "Consider a stewardship touch highlighting impact of their last gift.",
            "If recency > 12 months, classify as lapsed and propose reactivation.",
        ]
        steps = [
            "Create a follow-up task for personal outreach.",
            "Prepare suggested ask amounts based on lifetime and most recent gift.",
        ]
        lines.append("")
        lines.append(header("AI Insights"))
        lines.extend([f"- {i}" for i in insights])
        lines.append("")
        lines.append(header("Next Steps"))
        lines.extend([f"- {s}" for s in steps])
        return "\n".join(lines)

    async def tool_find_prospects(self, parameters: str = "") -> str:
        await self.ensure_connected()
        # Simple heuristic: donors with lifetime > $5k and no gift in last 12 months
        soql = SOQLBuilder.lapsed_donors(months=12, limit=DEFAULT_LIMIT)
        try:
            res = await self.sf.soql(soql)
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to find prospects. {e}"
        records = res.get("records", [])
        # Score based on lifetime giving (proxy)
        scored = []
        for r in records:
            lifetime = r.get("LifetimeGiving") or 0
            try:
                score = float(lifetime) / 1000.0
            except Exception:
                score = 0.0
            r["ProspectScore"] = round(score, 2)
            scored.append(r)
        scored.sort(key=lambda x: x.get("ProspectScore", 0), reverse=True)
        insights = [
            "Upgrade candidates prioritized by lifetime giving and lapse status.",
            "Use personalized asks ~10-20% above last gift for warm leads.",
        ]
        steps = [
            "Schedule 3 outreach tasks with tailored messaging.",
            "Add top prospects to an upgrade cadence.",
        ]
        return self._format_records("Prospect Candidates", scored[:DEFAULT_LIMIT], insights, steps)

    # --------- Write functions (basic validations + minimal implementation) ---------
    async def tool_create_task(self, task_details: Dict[str, Any]) -> str:
        await self.ensure_connected()
        required = ["Subject", "WhoId"]
        missing = [k for k in required if not task_details.get(k)]
        if missing:
            return header("Validation Error") + f"\n- Missing fields: {', '.join(missing)}"
        try:
            res = await self.sf.create("Task", task_details)
            return header("Task Created") + f"\n- Id: {res.get('id')}\n- Subject: {task_details.get('Subject')}\n- WhoId: {task_details.get('WhoId')}"
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to create task. {e}"

    async def tool_create_contact(self, contact_info: Dict[str, Any]) -> str:
        await self.ensure_connected()
        if not contact_info.get("LastName"):
            return header("Validation Error") + "\n- LastName is required"
        try:
            res = await self.sf.create("Contact", contact_info)
            return header("Contact Created") + f"\n- Id: {res.get('id')}\n- Name: {contact_info.get('FirstName','')} {contact_info.get('LastName','')}".strip()
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to create contact. {e}"

    async def tool_create_opportunity(self, opportunity_details: Dict[str, Any]) -> str:
        await self.ensure_connected()
        required = ["Name", "StageName", "CloseDate", "Amount"]
        missing = [k for k in required if not opportunity_details.get(k)]
        if missing:
            return header("Validation Error") + f"\n- Missing fields: {', '.join(missing)}"
        try:
            res = await self.sf.create("Opportunity", opportunity_details)
            return header("Opportunity Created") + f"\n- Id: {res.get('id')}\n- Name: {opportunity_details.get('Name')}\n- Amount: {fmt_currency(opportunity_details.get('Amount'))}"
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to create opportunity. {e}"

    async def tool_log_interaction(self, contact_id: str, interaction_details: Dict[str, Any]) -> str:
        await self.ensure_connected()
        if not contact_id:
            return header("Validation Error") + "\n- contact_id is required"
        data = {"Subject": interaction_details.get("Subject", "Donor Outreach"), "WhoId": contact_id}
        if interaction_details.get("Description"):
            data["Description"] = interaction_details["Description"]
        return await self.tool_create_task(data)

    async def tool_update_contact_stage(self, contact_id: str, stage: str) -> str:
        await self.ensure_connected()
        if not contact_id or not stage:
            return header("Validation Error") + "\n- contact_id and stage are required"
        try:
            await self.sf.update("Contact", contact_id, {"LifecycleStage__c": stage})
            return header("Contact Updated") + f"\n- Id: {contact_id}\n- Stage: {stage}"
        except Exception as e:
            return header("Salesforce Error") + f"\n- Unable to update contact. {e}"

    async def tool_bulk_update_records(self, records_data: List[Dict[str, Any]]) -> str:
        await self.ensure_connected()
        if not records_data:
            return header("Validation Error") + "\n- records_data is empty"
        # For MVP, process sequentially (safe) — can be optimized via Bulk API
        updated = 0
        errors: List[str] = []
        for r in records_data:
            sobj = r.get("sobject")
            rid = r.get("id")
            fields = r.get("fields", {})
            if not sobj or not rid or not fields:
                errors.append(f"Missing data for record: {r}")
                continue
            try:
                await self.sf.update(sobj, rid, fields)
                updated += 1
            except Exception as e:
                errors.append(f"{sobj}:{rid} -> {e}")
        lines = [header("Bulk Update Summary"), f"- Updated: {updated}"]
        if errors:
            lines.append("- Errors:")
            lines.extend([f"  - {e}" for e in errors])
        return "\n".join(lines)

    # ------------------------ Server lifecycle ------------------------
    async def start(self) -> None:
        if not MCP_AVAILABLE or stdio_server is None:
            logger.warning("MCP library not available; cannot start stdio server. Ensure 'mcp' is installed.")
            return

        # Preferred: FastMCP path
        if self.fastmcp is not None:
            m = self.fastmcp

            # Single general-purpose tool: let the LLM generate SOQL
            @m.tool()
            async def run_soql(query: str, limit: int = DEFAULT_LIMIT) -> str:  # type: ignore
                return await self.tool_run_soql(query, limit)

            # Generic creator for any sObject
            @m.tool()
            async def create_record(sobject: str, fields: Dict[str, Any]) -> str:  # type: ignore
                return await self.tool_create_record(sobject, fields)

            # Generic updater for any sObject
            @m.tool()
            async def update_record(sobject: str, record_id: str, fields: Dict[str, Any]) -> str:  # type: ignore
                return await self.tool_update_record(sobject, record_id, fields)

            # Do not connect to Salesforce here; connect lazily on first tool call

            await m.run_stdio_async()
            return

        # Fallback: legacy Server API path (only if it has 'tool')
        if self.server is None or not hasattr(self.server, "tool"):
            logger.error("MCP Server API without FastMCP and no 'tool' decorator available. Please upgrade 'mcp'.")
            return

        # Single general-purpose tool: let the LLM generate SOQL
        @self.server.tool()  # type: ignore
        async def run_soql(query: str, limit: int = DEFAULT_LIMIT) -> str:  # type: ignore
            return await self.tool_run_soql(query, limit)

        # Generic creator for any sObject
        @self.server.tool()  # type: ignore
        async def create_record(sobject: str, fields: Dict[str, Any]) -> str:  # type: ignore
            return await self.tool_create_record(sobject, fields)

        # Generic updater for any sObject
        @self.server.tool()  # type: ignore
        async def update_record(sobject: str, record_id: str, fields: Dict[str, Any]) -> str:  # type: ignore
            return await self.tool_update_record(sobject, record_id, fields)

        await self.sf.connect()
        async with stdio_server() as (read, write):  # type: ignore
            await self.server.run(read, write)  # type: ignore


async def main() -> None:
    srv = FundraisingServer()
    await srv.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
