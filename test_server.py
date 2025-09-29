import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("LOG_LEVEL", "DEBUG")

from fundraising_mcp_server import (
    build_soql_from_criteria,
    parse_amount,
    parse_timeframe,
    FundraisingServer,
)


class TestNLPParsing(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("over $1,000"), 1000.0)
        self.assertEqual(parse_amount("$5k"), 5000.0)
        self.assertEqual(parse_amount("2.5M"), 2500000.0)
        self.assertIsNone(parse_amount("no amount"))

    def test_parse_timeframe(self):
        tf = parse_timeframe("last 6 months")
        self.assertIsNotNone(tf)
        self.assertTrue((tf.end - tf.start).days >= 170)  # approx

    def test_soql_lapsed(self):
        soql, meta = build_soql_from_criteria("lapsed donors")
        self.assertIn("FROM Contact", soql)
        self.assertEqual(meta["segment"], "lapsed_donors")

    def test_soql_major(self):
        soql, meta = build_soql_from_criteria("major donors over $5000")
        self.assertIn("HAVING SUM", soql)
        self.assertEqual(meta["amount"], 5000.0)

    def test_soql_recent(self):
        soql, meta = build_soql_from_criteria("recent donors from last 3 months")
        self.assertIn("LAST_N_DAYS", soql)
        self.assertEqual(meta["months"], 3)


class TestServerTools(unittest.IsolatedAsyncioTestCase):
    @patch("fundraising_mcp_server.SalesforceClient")
    async def test_query_donors(self, MockSF):
        mock = MockSF.return_value
        mock.soql = MagicMock(return_value={
            "records": [
                {"Name": "John Doe", "Email": "john@example.com", "LifetimeGiving": 2500, "LastGiftDate": "2024-01-15"}
            ]
        })
        srv = FundraisingServer()
        srv.sf = mock
        out = await srv.tool_query_donors("lapsed donors")
        self.assertIn("Donor Results", out)
        self.assertIn("John Doe", out)

    @patch("fundraising_mcp_server.SalesforceClient")
    async def test_get_donor_profile(self, MockSF):
        mock = MockSF.return_value
        mock.soql = MagicMock(return_value={
            "records": [
                {
                    "Id": "003XYZ",
                    "Name": "Jane Smith",
                    "Email": "jane@example.com",
                    "Phone": "555-5555",
                    "MailingCity": "SF",
                    "MailingState": "CA",
                    "LifetimeGiving": 10000,
                    "RecentGifts": [
                        {"Amount": 5000, "CloseDate": "2024-01-10", "StageName": "Closed Won"}
                    ],
                }
            ]
        })
        srv = FundraisingServer()
        srv.sf = mock
        out = await srv.tool_get_donor_profile("Jane")
        self.assertIn("Donor Profile", out)
        self.assertIn("Jane Smith", out)
        self.assertIn("Recent Gifts", out)

    @patch("fundraising_mcp_server.SalesforceClient")
    async def test_create_task_validation(self, MockSF):
        srv = FundraisingServer()
        out = await srv.tool_create_task({"WhoId": "003XYZ"})
        self.assertIn("Validation Error", out)


if __name__ == "__main__":
    unittest.main()
