"""Offline feed classification regressions; no source requests."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_release_drift as drift

class FreshnessClassificationTests(unittest.TestCase):
    def test_work_correction_and_unknown_are_separate(self):
        for identifier, expected in [
            ('https://www.legislation.gov.uk/id/uksi/2026/901', 'legal-work'),
            ('https://www.legislation.gov.uk/uksi/2026/901/pdfs/uksics_20260901_en_001.pdf', 'correction-notice'),
            ('https://www.legislation.gov.uk/correction/uksi/2026/901', 'correction-notice'),
            ('https://www.legislation.gov.uk/not-a-work', 'unresolved-feed-entry')]:
            with self.subTest(identifier=identifier):
                self.assertEqual(drift.classify_feed_record({'id':identifier, 'title':'Correction slip'}), expected)

    def test_only_missing_works_are_counted_as_new_works(self):
        rows = [
            {'id':'https://www.legislation.gov.uk/id/uksi/2026/901', 'route':'dataset/a'},
            {'id':'https://www.legislation.gov.uk/uksi/2026/901/correction.pdf', 'route':'dataset/b'},
            {'id':'https://www.legislation.gov.uk/unknown', 'route':'dataset/c'}]
        with patch.object(drift.legislation,'parse_entries',return_value=rows), patch.object(drift,'route_exists',return_value=False) as exists, patch.object(Path,'read_text',return_value='{}'):
            result, failures = drift.new_work_observation(b'')
        self.assertEqual(result['new_works_count'],1)
        self.assertEqual(result['correction_notice_count'],1)
        self.assertEqual(result['unresolved_entry_count'],1)
        self.assertEqual(exists.call_count,1)
        self.assertEqual(len(failures),3)

if __name__ == '__main__': unittest.main()
