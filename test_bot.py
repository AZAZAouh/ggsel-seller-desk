import unittest
from bot import Bot


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.bot = Bot({'TELEGRAM_OWNER_ID': '100000001'}, ':memory:')
        self.sent = []
        self.bot.send = lambda text, rows: self.sent.append((text, rows))
        self.bot.tg = lambda *args, **kwargs: None

    def tearDown(self):
        self.bot.db.close()

    def test_private_access_only(self):
        for sender, chat in [(12, 100000001), (100000001, -123)]:
            self.bot.handle({'message': {'from': {'id': sender}, 'chat': {'id': chat}}})
        self.assertEqual(self.sent, [])

    def test_independent_switches_and_idempotent_callbacks(self):
        self.bot.show('off:104005409')
        self.bot.show('off:104005409')
        self.assertFalse(self.bot.get('sync:104005409'))
        self.assertIsNone(self.bot.get('sync:104005436'))

        # Per-card delivery switches are also independent across the two 7-day cards and 1-month card
        self.bot.show('deliv_on:104005409')
        self.assertTrue(self.bot.get('delivery:104005409'))
        self.assertFalse(self.bot.get('delivery:104005436', False))
        self.assertFalse(self.bot.get('delivery:103376334', False))

    def test_delivery_cannot_be_enabled(self):
        self.bot.show('delivery:104005409')
        self.assertIn('недоступны', self.sent[-1][0])
        self.assertFalse(self.bot.live_purchases_active())
        self.assertFalse(self.bot.get('delivery:104005409', False))

    def test_sync_preserves_other_product_snapshot(self):
        p = self.bot.products[0]
        self.bot.supplier = lambda _: {'variants': [{'id': p['supplier_variant_id'], 'prices': {'usd': .25}, 'available_quantity': 18}]}
        self.bot.sync(p)
        self.assertEqual(self.bot.get('catalog:104005409')['variant']['available_quantity'], 18)
        self.assertIsNone(self.bot.get('catalog:104005436'))


if __name__ == '__main__':
    unittest.main()
