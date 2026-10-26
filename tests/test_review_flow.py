import unittest
from leadhunter.review_flow import decide, mark_sent, prioritized_leads, email_ready


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.a = {"id": "node/42", "name": "Test A"}
        self.b = {"id": "way/43", "name": "Test B"}
        self.c = {"id": "relation/44", "name": "Test C"}

    def test_yes_is_email_pending_not_sent(self):
        state = decide({}, "node/42", "yes")
        self.assertEqual(state["node/42"], "email_pending")
        self.assertFalse(email_ready(state, "node/42"))

    def test_mail_requires_sender_recipient_and_eligibility(self):
        state = decide({}, "node/42", "yes")
        self.assertFalse(email_ready(state, "node/42", recipient_verified=True,
                                     sender_configured=True))
        self.assertTrue(email_ready(state, "node/42", recipient_verified=True,
                                    sender_configured=True, lawful_basis_verified=True))

    def test_no_removes_from_list(self):
        state = decide({}, "node/42", "no")
        self.assertEqual(prioritized_leads(state, [self.a, self.b]), [self.b])
        self.assertEqual(decide(state, "node/42", "later"), state)

    def test_later_is_first_in_next_scan(self):
        state = decide({}, "node/42", "later")
        result = prioritized_leads(state, [self.b, self.a, self.c])
        self.assertEqual([x["id"] for x in result],
                         ["node/42", "way/43", "relation/44"])

    def test_later_twice_stays_deferred(self):
        state = decide({}, "node/42", "later")
        state = decide(state, "node/42", "later")
        self.assertEqual(prioritized_leads(state, [self.b, self.a])[0]["id"],
                         "node/42")

    def test_held_lead_retrieved_from_private_fallback(self):
        state = decide({}, "node/42", "later")
        result = prioritized_leads(state, [self.b], deferred_fallback=[self.a])
        self.assertEqual(result[0]["id"], "node/42")

    def test_duplicate_yes_is_idempotent(self):
        state = decide({}, "node/42", "yes")
        self.assertEqual(decide(state, "node/42", "yes"), state)

    def test_email_sent_is_terminal(self):
        state = decide({}, "node/42", "yes")
        self.assertEqual(mark_sent(state, "node/42", delivered=False), state)
        state = mark_sent(state, "node/42", delivered=True)
        self.assertEqual(state["node/42"], "email_sent")
        self.assertEqual(decide(state, "node/42", "yes"), state)
        self.assertFalse(email_ready(state, "node/42"))

    def test_rejected_cannot_be_marked_sent(self):
        with self.assertRaises(ValueError):
            mark_sent(decide({}, "node/42", "no"), "node/42", delivered=True)

    def test_invalid_id_or_action_rejected(self):
        for lid in ["42", "../node/3", "node/-3", "mail@example.com"]:
            with self.assertRaises(ValueError):
                decide({}, lid, "yes")
        with self.assertRaises(ValueError):
            decide({}, "node/42", "unknown")
        with self.assertRaises(ValueError):
            prioritized_leads({}, [self.a], maximum=-1)

    def test_limit_and_dedupe(self):
        result = prioritized_leads({}, [self.a, self.a, self.b, self.c], maximum=2)
        self.assertEqual([x["id"] for x in result], ["node/42", "way/43"])

    def test_legacy_seen_leads_receive_buttons_only_once(self):
        result = prioritized_leads({}, [], legacy_fallback=[self.a, self.b])
        self.assertEqual([x['id'] for x in result], ['node/42', 'way/43'])
        recorded = {'node/42': 'review', 'way/43': 'rejected'}
        self.assertEqual(prioritized_leads(recorded, [], legacy_fallback=[self.a, self.b]), [])

    def test_priority_deferred_new_then_legacy(self):
        states = {'relation/44': 'deferred'}
        result = prioritized_leads(states, [self.b], deferred_fallback=[self.c],
                                   legacy_fallback=[self.a], maximum=3)
        self.assertEqual([x['id'] for x in result],
                         ['relation/44', 'way/43', 'node/42'])

    def test_legacy_dedupe_and_never_resurface_approved(self):
        states = {'node/42': 'email_pending'}
        self.assertEqual(prioritized_leads(states, [], legacy_fallback=[self.a]), [])
        self.assertEqual([x['id'] for x in prioritized_leads(
            {}, [self.b], legacy_fallback=[self.b, self.c])],
            ['way/43', 'relation/44'])

    def test_no_input_mutation(self):
        original = {"node/42": "deferred"}
        state = decide(original, "way/43", "no")
        self.assertEqual(original, {"node/42": "deferred"})
        self.assertIsNot(state, original)
