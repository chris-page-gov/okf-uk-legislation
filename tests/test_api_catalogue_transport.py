import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_uk_government_api_okf import (
    DEFAULT_OS_API_ROOT, MAX_OS_DOCUMENT_BYTES, discover_os_documents,
)


class CatalogueTransportTests(unittest.TestCase):
    def test_discovery_uses_the_bounded_publisher_transport(self):
        child = DEFAULT_OS_API_ROOT + "catalogue"
        response = {
            "status": 200,
            "error": None,
            "truncated": False,
            "body": json.dumps({
                "links": [
                    {"href": child, "type": "application/json", "rel": "api-grouping"},
                    {"href": child, "type": "application/json", "rel": "landing-page"},
                    {"href": "https://example.org/catalogue", "type": "application/json", "rel": "api-grouping"},
                ],
            }).encode(),
        }
        with patch("capture_whole_law_route_replacements.fetch_public_request", return_value=response) as fetch:
            documents = discover_os_documents()
        self.assertEqual([call.kwargs["url"] for call in fetch.call_args_list], [DEFAULT_OS_API_ROOT, child])
        self.assertEqual(list(documents), [DEFAULT_OS_API_ROOT, child])
        for call in fetch.call_args_list:
            self.assertEqual(call.kwargs["allowed_hosts"], {"api.os.uk"})
            self.assertEqual(call.kwargs["max_body_bytes"], MAX_OS_DOCUMENT_BYTES)

    def test_incomplete_document_remains_a_failed_observation(self):
        response = {"status": 200, "error": None, "truncated": True, "body": b"{}"}
        with patch("capture_whole_law_route_replacements.fetch_public_request", return_value=response) as fetch:
            documents = discover_os_documents()
        fetch.assert_called_once()
        self.assertIn("complete successful response", documents[DEFAULT_OS_API_ROOT]["fetch_error"])

    def test_total_response_budget_stops_queued_requests(self):
        child = DEFAULT_OS_API_ROOT + "catalogue"
        body = json.dumps({
            "links": [{"href": child, "type": "application/json", "rel": "api-grouping"}],
        }).encode()
        response = {"status": 200, "error": None, "truncated": False, "body": body}
        with (
            patch("build_uk_government_api_okf.MAX_OS_DISCOVERY_BYTES", len(body)),
            patch("capture_whole_law_route_replacements.fetch_public_request", return_value=response) as fetch,
        ):
            documents = discover_os_documents()
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["max_body_bytes"], len(body))
        self.assertIn("response budget", documents[child]["fetch_error"])
