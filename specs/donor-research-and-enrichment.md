---
title: donor-research-and-enrichment
description: Conduct deep external research on specific donors to supplement Salesforce data
allowed-tools: fundraisingaimcp MCP server, web_search, web_fetch
---

# Donor Research and Enrichment

## Workflow

Using the fundraisingaimcp MCP server and web research tools, compile comprehensive external intelligence on specified donor(s) to supplement internal Salesforce data.

**Retrieve Salesforce Foundation:**
- Accept donor name/ID as input
- Pull basic profile from Salesforce:
  - Current employer/organization
  - Title/role
  - Location
  - Giving history summary
  - Known interests
  - Last contact date and notes

**Conduct External Research:**

*Individual Donors:*
- Search LinkedIn for professional profile:
  - Current role and company
  - Career progression and job changes
  - Educational background
  - Professional connections (especially to your organization)
  - Recent posts or activity indicating interests
  - Any life events or milestones mentioned
- General web search for public information:
  - News mentions or press coverage
  - Awards, honors, or recognition
  - Board memberships or community involvement
  - Speaking engagements or publications
  - Social media presence (if publicly available)
- Business/company research (if applicable):
  - Company performance and news
  - Leadership changes
  - Expansion or contraction signals

*Corporate/Foundation Donors:*
- Company website research:
  - Mission and values alignment
  - CSR/giving priorities
  - Recent initiatives or announcements
  - Key decision-makers
  - Financial health indicators
- Foundation website/990 review:
  - Giving priorities and geographic focus
  - Grant size ranges
  - Application deadlines and requirements
  - Recently funded organizations
  - Board composition
- Industry news and trends:
  - Recent company/foundation announcements
  - Industry challenges or opportunities
  - Competitive landscape

**Wealth Indicators (if appropriate):**
- Public records of property ownership, business investments
- Board positions at other organizations
- Philanthropic activity at peer organizations
- Note: Maintain ethical boundaries and respect privacy

**Synthesize Intelligence:**
- Identify connection points to your organization's work
- Flag any time-sensitive opportunities (job promotion, company success, award)
- Note potential concerns (company layoffs, negative press)
- Suggest cultivation or stewardship approaches based on findings

**Create markdown enrichment report including:**
- Executive summary of key findings
- Professional background and current situation
- Relevant life/career updates since last contact
- Giving capacity indicators (when appropriate)
- Connection points to your mission and programs
- Potential conversation topics or cultivation strategies
- Time-sensitive opportunities or concerns
- Recommended next steps for engagement
- Sources cited for all external information

## Settings

- goose_provider: "anthropic"
- goose_model: "claude-sonnet-4-20250514"
- temperature: 0.5
