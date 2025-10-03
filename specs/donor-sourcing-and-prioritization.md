---
title: donor-sourcing-and-prioritization
description: Identify and prioritize donors for outreach based on strategic priorities and bandwidth
allowed-tools: fundraisingaimcp MCP server
---

# Donor Sourcing and Prioritization

## Workflow

Using the fundraisingaimcp MCP server, identify which donors to focus on for outreach, aligned with strategic priorities and available capacity.

**Understand Strategic Context:**
- Prompt for or reference current strategic priorities (e.g., "retention focus," "major gift cultivation," "monthly donor growth")
- Ask about timeframe (this week, this month, this quarter)
- Ask about bandwidth (how many donors can realistically be contacted?)
- Identify which staff member is requesting (to filter by relationship ownership)

**Source Donor Pool:**
- Query Salesforce for donors matching strategic priorities:
  - If strategy emphasizes retention → lapsed donors, decreasing givers
  - If strategy emphasizes upgrades → donors giving below capacity, multi-year donors
  - If strategy emphasizes acquisition → recent first-time donors needing stewardship
  - If strategy emphasizes major gifts → high-capacity prospects in cultivation
- For each potential donor, retrieve:
  - Complete giving history (Opportunities: Amount, CloseDate, StageName, RecordType)
  - Recent engagement (Campaign Members, Event Attendees, Volunteer records)
  - Contact activity log (Tasks and Events with dates, subjects, descriptions)
  - Communication preferences (preferred contact method, best times)
  - Interests and program affinities (custom fields or tags)
  - Relationship owner (assigned staff member)
  - Existing open tasks

**Prioritize Donors:**
- Categorize each donor by outreach type needed:
  - **Stewardship**: Active donors needing regular touchpoint (no ask)
  - **Re-engagement**: Lapsed or decreasing donors
  - **Cultivation**: Prospects ready for upgrade conversation
  - **Renewal**: Recurring gifts or grants coming due
- Score/rank donors based on:
  - Strategic fit (matches current organizational priorities)
  - Urgency (long time since last contact, gift renewal date approaching)
  - Capacity/potential impact (donor level, giving potential)
  - Relationship strength (board connections, major gift prospects)
  - Staff capacity (existing workload, open tasks)
- Filter to realistic outreach list based on stated bandwidth

**Note External Enrichment Opportunities:**
- For top-priority donors, suggest external data to research:
  - LinkedIn profile (job changes, promotions, life events)
  - Company websites (for corporate donors)
  - News mentions or public information
  - Wealth screening data (if available in org)

**Create markdown report with:**
- Strategic context summary (goals driving this outreach)
- Top priority donor list (limited to stated bandwidth) with:
  - Donor name and giving level
  - Why they're a priority (category, urgency, strategic fit)
  - Key background info (giving history highlights, last contact)
  - Recommended outreach type and channel
  - Assigned relationship owner
- Secondary/future outreach list (if capacity allows later)
- Suggested external research for VIP donors

## Settings

- goose_provider: "anthropic"
- goose_model: "claude-sonnet-4-20250514"
- temperature: 0.4
