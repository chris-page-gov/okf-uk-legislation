from pathlib import Path
from hashlib import sha256
import json
from io import BytesIO
import tarfile
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_reader_transport as transport  # noqa: E402


class ReaderTransportTest(unittest.TestCase):
    def test_pages_tar_size_matches_gnu_archive_padding_and_long_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "site"
            (root / "nested").mkdir(parents=True)
            for index, size in enumerate((0, 1, 511, 512, 513)):
                (root / "nested" / str(index)).write_bytes(b"x" * size)
            (root / ("a" * 120)).write_bytes(b"long name")
            stream = BytesIO()
            with tarfile.open(fileobj=stream, mode="w", format=tarfile.GNU_FORMAT,
                              dereference=True) as archive:
                archive.add(root, arcname=".")
            self.assertEqual(len(stream.getvalue()), transport.pages_tar_size(root))
            (root / "unsafe-link").symlink_to(root / "nested" / "0")
            with self.assertRaisesRegex(ValueError, "non-regular member"):
                transport.pages_tar_size(root)

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


class CanonicalDescriptorParityTest(unittest.TestCase):
    def test_project_keeps_exact_descriptor_and_binds_source_and_typed_shard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {
                "name": "ukpga-2010-15",
                "document_uri": "https://www.legislation.gov.uk/ukpga/2010/15",
                "structure_url": "https://www.legislation.gov.uk/ukpga/2010/15/data.xml",
                "legislation_id_uri": "http://www.legislation.gov.uk/id/ukpga/2010/15",
            }
            shard = root / "data/works-0.json.gz"
            shard.parent.mkdir()
            before = transport.gzip_json([record])
            shard.write_bytes(before)
            manifest = {"chunks": {"datasets": ["data/works-0.json.gz"]}, "counts": {"works": 1}}
            transport.render_at(root / "data/manifest.json", manifest)
            locator = {"record_chunks": [{"path": "data/works-0.json.gz", "records": 1,
                       "sha256": sha256(before).hexdigest(), "compressed_bytes": len(before)}]}
            transport.render_at(root / "data/records/manifest.json", locator)
            performance = {"planes": {"work_records": {}}, "targeted_record_hydration": {},
                           "full_hydration": {"decoded_json_bytes_before_object_overhead": 1000},
                           "startup": {"control_plane_bytes": 1000}}
            transport.render_at(root / "data/performance.json", performance)
            descriptor = b'{ "entrypoints": {}, "schema": "okf-explorer-large-corpus.v1" }\n'
            (root / "okf-explorer.json").write_bytes(descriptor)
            execution = root / "whole-law/evaluation/executions/eval-76d593e3295063f2cbe5"
            execution.mkdir(parents=True)
            answer_bytes = b'{ "answers": [1,  2] }\n'
            (execution / "answers.json").write_bytes(answer_bytes)
            report_bytes = b"<html><code>answers.json</code></html>\n"
            (execution / "report.html").write_bytes(report_bytes)
            earlier = root / "whole-law/evaluation/executions/eval-1edbcf9ff765b952ee03"
            earlier.mkdir()
            (earlier / "answers.json").write_bytes(answer_bytes + b" \n")
            (earlier / "report.html").write_bytes(report_bytes)
            execution_index = json.dumps({"latest_run_id": "eval-76d593e3295063f2cbe5",
                "executions": [{"run_id": run} for run in (
                    "eval-76d593e3295063f2cbe5", "eval-1edbcf9ff765b952ee03")]}).encode()
            (execution.parent / "index.json").write_bytes(execution_index)
            whole_law_rows = [
                {"path": "evaluation/executions/eval-76d593e3295063f2cbe5/answers.json",
                 "bytes": len(answer_bytes), "sha256": sha256(answer_bytes).hexdigest()},
                {"path": "evaluation/executions/eval-76d593e3295063f2cbe5/report.html",
                 "bytes": len(report_bytes), "sha256": sha256(report_bytes).hexdigest()},
                {"path": "evaluation/executions/index.json",
                 "bytes": len(execution_index), "sha256": sha256(execution_index).hexdigest()},
            ]
            for name in ("okf-bundle.yamlld", "okf-bundle.jsonld", "okf-bundle.ttl"):
                body = (name + " fixture\n").encode()
                (root / "whole-law" / name).write_bytes(body)
                whole_law_rows.append({"path": name, "bytes": len(body), "sha256": sha256(body).hexdigest()})
            for name in ("answers.json", "report.html"):
                body = (earlier / name).read_bytes()
                whole_law_rows.append({"path": "evaluation/executions/eval-1edbcf9ff765b952ee03/" + name,
                    "bytes": len(body), "sha256": sha256(body).hexdigest()})
            (root / "whole-law/integrity.json").write_text(json.dumps({"files": whole_law_rows}), encoding="utf-8")
            source_checksums = transport.build_checksums(root)
            (root / "checksums.json").write_text(source_checksums)
            result = transport.project(root, "a" * 40)
            self.assertEqual(1, result["work_count"])
            self.assertEqual(descriptor, (root / "okf-explorer.json").read_bytes())
            receipt = json.loads((root / transport.RECEIPT).read_bytes())
            self.assertEqual("okf-legislation-reader-transport.v2", receipt["schema"])
            self.assertEqual(sha256(descriptor).hexdigest(), receipt["canonical_descriptor_sha256"])
            self.assertEqual(sha256(source_checksums.encode()).hexdigest(), receipt["source_checksums_sha256"])
            row, = receipt["work_shards"]
            self.assertEqual(sha256(before).hexdigest(), row["source_sha256"])
            self.assertEqual(sha256(shard.read_bytes()).hexdigest(), row["sha256"])
            self.assertNotEqual(row["source_sha256"], row["sha256"])
            typed, = json.loads(transport.inflate_single_gzip(shard))
            self.assertEqual("extension", typed["core_role"])
            self.assertEqual(record["legislation_id_uri"], typed["legislation_id_uri"])
            self.assertEqual("application/xml", typed["source_representations"][0]["source_access"]["media_type"])
