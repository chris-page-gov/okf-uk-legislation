from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_reader_transport as transport  # noqa: E402


class ReaderTransportTest(unittest.TestCase):
    def test_preserves_exact_welsh_expression_and_distinguishes_the_json_shortcut(self):
        work = "https://www.legislation.gov.uk/wsi/2026/99/made"
        xml = work + "/welsh/data.xml"
        record = {
            "name": "wsi-2026-99",
            "legislation_id_uri": "https://www.legislation.gov.uk/id/wsi/2026/99",
            "document_uri": work,
            "structure_url": xml,
            "source_api_url": xml,
            "manifestations": {"clml": xml},
        }
        transport_work = transport.typed_work(record)
        self.assertEqual(record["source_api_url"], xml)
        self.assertNotIn("source_api_url", transport_work)
        resource, = transport_work["source_representations"]
        self.assertEqual(resource["id"], "wsi-2026-99-clml-made-welsh")
        self.assertEqual(resource["source_access"]["url"], xml)
        self.assertEqual(resource["source_access"]["media_type"], "application/xml")
        self.assertEqual(resource["source_access"]["representation_version"], "made")
        self.assertEqual(
            transport.typed_work({**record, "source_api_url": work + "/data.json"})["source_api_url"],
            work + "/data.json",
        )

    def test_rejects_a_conflicting_work_or_requested_expression(self):
        work = "https://www.legislation.gov.uk/eur/2017/669"
        example = {
            "name": "eur-2017-669", "document_uri": work + "/2024-12-31",
            "legislation_id_uri": "https://www.legislation.gov.uk/id/eur/2017/669",
        }
        with self.assertRaisesRegex(ValueError, "CLML work"):
            transport.typed_work({**example, "structure_url": work.replace("669", "670") + "/data.xml"})
        with self.assertRaisesRegex(ValueError, "CLML version"):
            transport.typed_work({**example, "structure_url": work + "/2025-01-01/data.xml"})
