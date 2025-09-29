# AI Fundraising MCP Server (Salesforce/NPSP)

Production-ready MVP MCP server providing AI-powered fundraising intelligence integrated with Salesforce (NPSP). Designed for use with Claude Desktop/Goose via stdio.

## Features
- Async MCP stdio server using `mcp` Python library
- OAuth 2.0 (refresh token) to Salesforce; safe fallback to username/password (not recommended)
- NLP to SOQL for donor segments (lapsed, recent, first-time, major donors)
- Core tools: `query_donors`, `get_donor_profile`, `find_prospects`
- Additional write tools (create task/contact/opportunity, etc.) with validation
- Caching, logging, graceful error handling, API limit detection

## Quick Start
1. Create and configure a Salesforce Connected App (enable OAuth, refresh token).
2. Copy `.env.template` to `.env` and fill values.
3. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the server (stdio):
   ```bash
   python fundraising_mcp_server.py
   ```
5. Add to Claude Desktop (MCP): configure a stdio server pointing to the script.

## Environment
```
SF_CLIENT_ID=
SF_CLIENT_SECRET=
SF_REFRESH_TOKEN=
SF_INSTANCE_URL=
SF_DOMAIN=login  # or 'test' for sandbox
LOG_LEVEL=INFO
```

Optional (dev only):
```
SF_USERNAME=
SF_PASSWORD=
SF_SECURITY_TOKEN=
```

## Tools Overview
- query_donors(criteria)
- get_donor_profile(identifier)
- find_prospects(parameters)
- analyze_giving_patterns(timeframe)
- get_portfolio_metrics(user)
- create_contact(contact_info)
- create_opportunity(opportunity_details)
- log_interaction(contact_id, interaction_details)
- create_task(task_details)
- update_contact_stage(contact_id, stage)
- bulk_update_records(records_data)

## Testing
```bash
pytest -q
```

## Notes
- Default query limit: 25 records
- Date format: YYYY-MM-DD; Currency: $1,234.56
- NPSP fields used: `Contact`, `Contact.Name`, `Contact.Email`, `Opportunity`, `Amount`, `CloseDate`, `StageName`
