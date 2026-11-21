"""Durable coupon queue. GGsel transport must be connected separately.

An ambiguous send is never retried automatically: reconcile chat history first.
"""
import json
from pathlib import Path

MESSAGE = json.loads((Path(__file__).parent / 'config/review_coupon.json').read_text('utf-8'))['message']


class ReviewRewards:
    def __init__(self, connection):
        self.db = connection
        self.db.execute('''CREATE TABLE IF NOT EXISTS review_rewards (
            order_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,
            state TEXT NOT NULL, message TEXT NOT NULL, receipt TEXT)''')

    def status(self, order_id):
        row = self.db.execute(
            'SELECT state, receipt FROM review_rewards WHERE order_id=?',
            (str(order_id),),
        ).fetchone()
        return {'state': row[0], 'receipt': row[1]} if row else None

    def observe(self, order_id, chat_id, review_present):
        if review_present is not True:
            return
        if not order_id or not chat_id:
            raise ValueError('Verified order and matching chat required')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO review_rewards VALUES (?, ?, ?, ?, NULL)',
                            (str(order_id), str(chat_id), 'pending', MESSAGE))

    def reconcile(self, order_id, found_receipt=None, confirmed_absent=False):
        if found_receipt and confirmed_absent:
            raise ValueError('Cannot be both found and absent')
        oid = str(order_id)
        if found_receipt:
            with self.db:
                updated = self.db.execute(
                    "UPDATE review_rewards SET state='sent', receipt=? WHERE order_id=? AND state IN ('pending', 'unknown', 'sending')",
                    (str(found_receipt), oid),
                ).rowcount
            return 'sent' if updated else None
        if confirmed_absent is True:
            with self.db:
                updated = self.db.execute(
                    "UPDATE review_rewards SET state='pending' WHERE order_id=? AND state IN ('unknown', 'sending')",
                    (oid,),
                ).rowcount
            return 'pending' if updated else None
        return None

    def deliver(self, order_id, send):
        # Commit the claim before the external call. A crash stays in sending.
        with self.db:
            claimed = self.db.execute("UPDATE review_rewards SET state='sending' WHERE order_id=? AND state='pending'",
                                      (str(order_id),)).rowcount
        if not claimed:
            return False
        chat, message = self.db.execute('SELECT chat_id, message FROM review_rewards WHERE order_id=?',
                                       (str(order_id),)).fetchone()
        try:
            receipt = send(chat, message)
            if not receipt:
                raise ValueError('No confirmed message receipt')
        except Exception:
            with self.db:
                self.db.execute("UPDATE review_rewards SET state='unknown' WHERE order_id=?", (str(order_id),))
            return False
        with self.db:
            self.db.execute("UPDATE review_rewards SET state='sent', receipt=? WHERE order_id=?",
                            (str(receipt), str(order_id)))
        return True
