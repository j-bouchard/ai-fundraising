---
title: fundraising-data-analysis
description: Comprehensive analysis of fundraising performance and donor trends
allowed-tools: fundraisingaimcp MCP server
---

# Fundraising Data Analysis

## Workflow

Using the fundraisingaimcp MCP server, perform a comprehensive analysis of fundraising performance and donor behavior patterns.

**Revenue Analysis:**
- Total revenue by year, quarter, and month
- Revenue by source (individual, corporate, foundation, planned giving)
- Revenue by campaign or appeal
- Average gift size trends over time
- Comparison to prior year and multi-year trends

**Donor Retention Analysis:**
- Calculate retention rate (donors who gave this year AND last year / total donors last year)
- Identify lapsed donors (gave previously but not in past 12-18 months)
- New donor acquisition rate
- Multi-year donor retention cohorts
- Donor lifetime value calculations

**Donor Segmentation:**
- Donors by giving level tiers (LYBUNT, SYBUNT, first-time, loyal, major)
- Recency, Frequency, Monetary (RFM) analysis
- Monthly/recurring donors vs one-time
- Donors by engagement type (event attendees, volunteers, advocates)

**Pipeline and Moves Management:**
- Prospects in cultivation by stage
- Average time from identification to first gift
- Upgrade analysis (donors who increased giving)
- Downgrade/decreased giving trends

**Campaign Performance:**
- Response rates by appeal type
- Cost per dollar raised by channel
- Monthly giving program growth
- Event ROI analysis

**Create a markdown report including:**
- Executive summary with key metrics and trends
- Detailed findings for each analysis area
- Visual data representations (tables showing trends)
- Red flags or concerns requiring attention
- Opportunities identified (segments to target, successful patterns to replicate)
- Specific actionable recommendations prioritized by potential impact

## Settings

- goose_provider: "anthropic"
- goose_model: "claude-sonnet-4-20250514"  
- temperature: 0.4
