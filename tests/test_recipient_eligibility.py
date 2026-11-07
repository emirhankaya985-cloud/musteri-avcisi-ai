"""Synthetic eligibility records; never use an actual IYS identifier or customer."""
from datetime import datetime, timedelta, timezone
import unittest
from leadhunter.recipient_eligibility import eligible_recipient


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,1,12,0,tzinfo=timezone.utc)
        self.address="company@example.invalid"
        self.consent={"route":"consent","recipient":self.address,
            "evidence_ref":"owner-verified-document-1234",
            "verified_at":(self.now-timedelta(hours=1)).isoformat(),
            "opted_out":False, "consent_active":True}
        self.b2b={"route":"iys_verified_business","recipient":self.address,
            "evidence_ref":"verified-merchant-registration-123",
            "verified_at":(self.now-timedelta(hours=1)).isoformat(),
            "opted_out":False,"iys_rejected":False,
            "merchant_verified":True,"iys_registered":True}

    def test_missing_or_untrusted_osm_and_mx_do_not_grant_eligibility(self):
        self.assertFalse(eligible_recipient({"email":self.address,
              "email_check":"mx_present","email_source":"OSM business contact tag"},
              self.address, self.now))
        self.assertFalse(eligible_recipient({},self.address,self.now))
        self.assertFalse(eligible_recipient(
            {"marketing_eligibility":{"route":"iys_verified_business"}},
            self.address,self.now))

    def test_documented_consent_and_fresh_iys_can_be_eligible(self):
        self.assertTrue(eligible_recipient({"marketing_eligibility":self.consent},
                                           self.address,self.now))
        self.assertTrue(eligible_recipient({"marketing_eligibility":self.b2b},
                                           self.address,self.now))

    def test_nonmatching_recipient_optout_and_invalid_evidence_block(self):
        for value in (
           {**self.consent,"recipient":"other@example.invalid"},
           {**self.consent,"opted_out":True},
           {**self.consent,"consent_active":False},
           {**self.consent,"evidence_ref":""},
           {**self.consent,"verified_at":"2025-01-01T00:00:00Z"},
           {**self.b2b,"iys_rejected":True},
           {**self.b2b,"merchant_verified":False},
           {**self.b2b,"iys_registered":False},
           {**self.b2b,"verified_at":(self.now-timedelta(hours=30)).isoformat()},
           {**self.b2b,"route":"unknown"},
        ):
            with self.subTest(value=value):
                self.assertFalse(eligible_recipient({"marketing_eligibility":value},
                                                    self.address,self.now))

    def test_no_resend_after_prior_bounce_delay_or_uncertain_mail(self):
        for field in ("_auto_mail", "_mail"):
            for state in ("sending", "accepted", "uncertain"):
                lead={"marketing_eligibility":self.consent,field:{"state":state}}
                with self.subTest(field=field,state=state):
                    self.assertFalse(eligible_recipient(lead,self.address,self.now))
            for failure in ("failed", "delayed"):
                lead={"marketing_eligibility":self.consent,field:{
                    "state":"draft","delivery_feedback":{"state":failure}}}
                with self.subTest(field=field,failure=failure):
                    self.assertFalse(eligible_recipient(lead,self.address,self.now))

    def test_clean_draft_remains_eligible_only_with_real_evidence(self):
        lead={"marketing_eligibility":self.consent, "_auto_mail":{"state":"draft"}}
        self.assertTrue(eligible_recipient(lead,self.address,self.now))
        self.assertFalse(eligible_recipient({"_auto_mail":{"state":"draft"}},
                                            self.address,self.now))
        lead["_auto_mail"]["delivery_feedback"]=["invalid"]
        self.assertFalse(eligible_recipient(lead,self.address,self.now))

    def test_evidence_cannot_be_future_dated(self):
        candidate={**self.consent,"verified_at":(self.now+timedelta(minutes=2)).isoformat()}
        self.assertFalse(eligible_recipient({"marketing_eligibility":candidate},
                                            self.address,self.now))


if __name__=="__main__":
    unittest.main()
