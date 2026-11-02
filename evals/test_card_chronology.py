"""Dated declarations cannot support an assessment made before that use."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import card_contract
from test_delegated import observed_card


class ChronologyTests(unittest.TestCase):
    def test_future_observation_cannot_support_seen_or_repeated(self):
        for grade in ['Seen', 'Repeated']:
            value, records = observed_card(grade)
            records['O1']['date'] = '2026-11-02'  # Card is dated 2026-11-01.
            with self.subTest(grade=grade):
                self.assertEqual(len(card_contract.semantic_errors(value, records)), 6)

    def test_same_day_and_earlier_observations_retain_support(self):
        for day in ['2026-10-27', '2026-11-01']:
            value, records = observed_card('Repeated')
            records['O1']['date'] = day
            with self.subTest(day=day):
                self.assertEqual(card_contract.semantic_errors(value, records), [])

    def test_future_return_does_not_upgrade_a_past_observation(self):
        value, records = observed_card('Repeated')
        future = copy.deepcopy(records['O1']); future['date'] = '2026-11-02'
        records['O1']['unprompted_return'] = False
        records['future'] = future
        for criterion in value['criteria'].values():
            criterion['evidence_refs'].append('future')
        before = copy.deepcopy(records)
        self.assertEqual(len(card_contract.semantic_errors(value, records)), 6)
        self.assertEqual(records, before)

    def test_one_past_specific_record_can_still_support_seen(self):
        value, records = observed_card('Seen')
        records['future'] = copy.deepcopy(records['O1'])
        records['future']['date'] = '2026-11-02'
        for criterion in value['criteria'].values():
            criterion['evidence_refs'].append('future')
        self.assertEqual(card_contract.semantic_errors(value, records), [])


if __name__ == '__main__':
    unittest.main()
