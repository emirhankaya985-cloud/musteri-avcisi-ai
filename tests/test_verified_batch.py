import json
import unittest
from leadhunter.verified_batch import parse_batch, run


class VerifiedBatchTests(unittest.TestCase):
    def lead(self, **changes):
        return {'name':'Synthetic Salon','email':'info@salon.invalid',
                'website':'https://salon.invalid/','email_source':'https://salon.invalid/contact',
                'category':'Kuaför/berber','source_verified':True,**changes}

    def test_stable_site_identity_and_source_are_preserved(self):
        result = parse_batch(json.dumps([self.lead()]))[0]
        self.assertTrue(result['id'].startswith('website/'))
        self.assertEqual(result['email_source'],'https://salon.invalid/contact')
        other = parse_batch(json.dumps([self.lead(website='https://www.salon.invalid/other')]))[0]
        self.assertEqual(result['id'],other['id'])

    def test_cap_duplicate_and_unverified_sources_fail_before_send(self):
        for rows in ([],[self.lead()]*16,[self.lead(),self.lead()],
                     [self.lead(source_verified=False)],
                     [self.lead(email_source='https://directory.invalid/contact')],
                     [self.lead(name='Bad\nBcc: other')]):
            with self.assertRaises(ValueError):
                parse_batch(json.dumps(rows))

    def test_explicit_batch_gate_is_required(self):
        with self.assertRaises(RuntimeError):
            run({})
