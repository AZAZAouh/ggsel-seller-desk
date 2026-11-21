import sqlite3
import unittest
from review_rewards import ReviewRewards, MESSAGE


class ReviewRewardTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.queue = ReviewRewards(self.db)

    def tearDown(self):
        self.db.close()

    def test_no_review_no_coupon(self):
        self.queue.observe('1', 'chat', False)
        self.assertEqual(self.db.execute('SELECT count(*) FROM review_rewards').fetchone()[0], 0)

    def test_duplicate_review_sends_once(self):
        calls = []
        send = lambda chat, text: calls.append((chat, text)) or 'receipt'
        self.queue.observe('1', 'chat', True)
        self.assertTrue(self.queue.deliver('1', send))
        self.queue.observe('1', 'chat', True)
        self.assertFalse(self.queue.deliver('1', send))
        self.assertEqual(calls, [('chat', MESSAGE)])

    def test_ambiguous_send_never_retried(self):
        def timeout(*args):
            raise TimeoutError()
        self.queue.observe('1', 'chat', True)
        self.assertFalse(self.queue.deliver('1', timeout))
        self.assertFalse(ReviewRewards(self.db).deliver('1', lambda *_: self.fail('Duplicate send')))
        self.assertEqual(self.db.execute('SELECT state FROM review_rewards').fetchone()[0], 'unknown')

    def test_crashed_claim_not_replayed(self):
        self.queue.observe('1', 'chat', True)
        self.db.execute("UPDATE review_rewards SET state='sending'")
        self.db.commit()
        self.assertFalse(self.queue.deliver('1', lambda *_: self.fail('Duplicate send')))

    def test_reconcile_marks_sent_or_requeues_only_when_verified(self):
        self.queue.observe('2', 'chat2', True)
        self.db.execute("UPDATE review_rewards SET state='unknown' WHERE order_id='2'")
        self.db.commit()
        self.assertEqual(self.queue.reconcile('2', found_receipt='msg_99'), 'sent')
        self.assertFalse(self.queue.deliver('2', lambda *_: self.fail('Already in chat')))

        self.queue.observe('3', 'chat3', True)
        self.db.execute("UPDATE review_rewards SET state='unknown' WHERE order_id='3'")
        self.db.commit()
        self.assertEqual(self.queue.reconcile('3', confirmed_absent=True), 'pending')
        self.assertTrue(self.queue.deliver('3', lambda *_: 'msg_100'))
