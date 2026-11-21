import sqlite3
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from capcut_delivery import (
    CapCutCoordinator,
    DryRunChatAdapter,
    DryRunSupplierAdapter,
    RoboticVNSupplierClient,
    run_dry_run_verification,
)


class CapCutDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.supplier = DryRunSupplierAdapter(initial_usd=10.00)
        self.chat = DryRunChatAdapter(image_supported=True)
        self.alerts = []
        self.engine = CapCutCoordinator(self.db, self.supplier, self.chat, self.alerts.append, mode_override='dry_run')
        self.now = datetime(2026, 11, 18, 0, 0, tzinfo=ZoneInfo('Europe/Warsaw'))
        self.paid_at = (self.now - timedelta(days=1)).isoformat()

    def tearDown(self):
        self.db.close()

    def test_new_order_and_duplicate_replay_buy_once_and_send_five_steps_in_order(self):
        self.engine.set_delivery_enabled('104005409', True)
        order = {'id': '7001', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1', 'date_pay': self.paid_at}

        first = self.engine.process_order(order)
        second = self.engine.process_order(order)

        self.assertEqual(first['action'], 'completed')
        self.assertEqual(second['action'], 'already_completed')
        self.assertEqual(self.supplier.create_calls, 1)
        self.assertEqual(len(self.supplier.orders), 1)

        msgs = self.chat.list_messages('7001')
        self.assertEqual(len(msgs), 5)
        self.assertIn('Email:', msgs[0]['message'])
        self.assertIn('Continue with email', msgs[1]['message'])
        self.assertIn('QR', msgs[2]['message'])
        self.assertTrue(all(not m['is_img'] and 't.me/' not in m['message'] for m in msgs))
        self.assertIn('слово «АДМИНИСТРАТОР»', msgs[3]['message'])
        self.assertIn('оставите отзыв', msgs[4]['message'])

        # Owner gets one combined completion notification with updated RoboticVN balance
        self.assertEqual(len(self.alerts), 1)
        self.assertIn('7001', self.alerts[0])
        self.assertIn('9.75 USD', self.alerts[0])

    def test_order_id_persisted_before_supplier_call(self):
        self.engine.set_delivery_enabled('104005409', True)
        observed_in_db_during_purchase = []
        orig_create = self.supplier.create_order

        defwrapped = lambda *a, **kw: (
            observed_in_db_purchase := self.db.execute(
                "SELECT order_id, status FROM capcut_orders WHERE order_id='7009'"
            ).fetchone(),
            observed_in_db_during_purchase.append(observed_in_db_purchase),
            orig_create(*a, **kw),
        )[-1]
        self.supplier.create_order = defwrapped

        self.engine.process_order({'id': '7009', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1'})
        self.assertEqual(observed_in_db_during_purchase, [('7009', 'purchasing')])

    def test_disabled_weekly_card_and_non_capcut_products_do_not_purchase(self):
        # Enable first weekly card 104005409, keep second weekly card 104005436 disabled
        self.engine.set_delivery_enabled('104005409', True)
        self.engine.set_delivery_enabled('104005436', False)

        res_disabled = self.engine.process_order({'id': '7002', 'item_id': '104005436', 'invoice_state': 3, 'cnt_goods': '1'})
        res_canva = self.engine.process_order({'id': '7003', 'item_id': '103156673', 'invoice_state': 3, 'cnt_goods': '1'})
        res_duolingo = self.engine.process_order({'id': '7004', 'item_id': '103203974', 'invoice_state': 3, 'cnt_goods': '1'})
        res_refunded = self.engine.process_order({'id': '7005', 'item_id': '104005409', 'invoice_state': 5, 'cnt_goods': '1'})

        self.assertEqual(res_disabled['action'], 'card_disabled')
        self.assertEqual(res_canva['action'], 'ignored_product')
        self.assertEqual(res_duolingo['action'], 'ignored_product')
        self.assertEqual(res_refunded['action'], 'ignored_state')
        self.assertEqual(self.supplier.create_calls, 0)

    def test_supplier_timeout_reconciles_existing_purchase_without_second_buy(self):
        self.engine.set_delivery_enabled('103376334', True)
        self.supplier.fail_next_create_after_commit = True

        order = {'id': '7010', 'item_id': '103376334', 'invoice_state': 3, 'cnt_goods': '1', 'date_pay': self.paid_at}
        first = self.engine.process_order(order)
        self.assertEqual(first['action'], 'purchase_uncertain')
        self.assertEqual(self.supplier.create_calls, 1)
        self.assertIn('7010', self.alerts[-1])
        self.assertIn('supplier_purchase', self.alerts[-1])

        # Reprocessing reconciles with RoboticVN, adopts the single order, and finishes all 5 steps
        retry = self.engine.process_order(order)
        self.assertEqual(retry['action'], 'reconciled_and_completed')
        self.assertEqual(self.supplier.create_calls, 1)
        self.assertEqual(len(self.supplier.orders), 1)
        self.assertEqual(len(self.chat.list_messages('7010')), 5)

    def test_chat_failure_reports_exact_step_and_resumes_without_rebuying(self):
        self.engine.set_delivery_enabled('104005409', True)
        self.chat.fail_on_step_text = 'QR'

        order = {'id': '7020', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1'}
        failed = self.engine.process_order(order)
        self.assertEqual(failed['action'], 'failed_step')
        self.assertEqual(failed['step'], 'login_instruction')
        self.assertIn('7020', self.alerts[-1])
        self.assertIn('login_instruction', self.alerts[-1])
        self.assertEqual(self.supplier.create_calls, 1)
        self.assertEqual(len(self.chat.list_messages('7020')), 2)  # account + email instructions already sent

        resumed = self.engine.process_order(order)
        self.assertEqual(resumed['action'], 'completed')
        self.assertEqual(self.supplier.create_calls, 1)
        self.assertEqual(len(self.chat.list_messages('7020')), 5)

    def test_delivery_completes_without_image_transport(self):
        chat_no_img = DryRunChatAdapter(image_supported=False)
        engine = CapCutCoordinator(self.db, self.supplier, chat_no_img, self.alerts.append, mode_override='dry_run')
        engine.set_delivery_enabled('104005409', True)

        res = engine.process_order({'id': '7030', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1'})
        self.assertEqual(res['action'], 'completed')
        self.assertEqual(self.supplier.create_calls, 1)

    def test_buyer_problem_keyword_alerts_owner_without_leaking_credentials(self):
        self.engine.set_delivery_enabled('104005409', True)
        self.engine.process_order({'id': '7040', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1'})
        self.alerts.clear()

        # Seller's own support instruction already contains «проблема» — must NOT trigger!
        self.assertEqual(self.engine.scan_buyer_messages('7040'), [])
        self.assertEqual(self.alerts, [])

        # Buyer sends «Проблема!» (with GGsel's buyer=1, seller=1 quirk)
        self.chat.inject_buyer_message('7040', 'Администратор, нужна помощь!', message_id=55501)
        first_scan = self.engine.scan_buyer_messages('7040')
        repeat_scan = self.engine.scan_buyer_messages('7040')

        self.assertEqual(first_scan, ['7040:55501'])
        self.assertEqual(repeat_scan, [])
        self.assertEqual(len(self.alerts), 1)
        self.assertIn('7040', self.alerts[0])
        self.assertNotIn('DryRunPass', self.alerts[0])

    def test_daily_warsaw_review_schedule_and_single_coupon_per_order(self):
        orders = [
            {
                'id': '8001',
                'item_id': '104005409',
                'invoice_state': 3,
                'date_pay': (self.now - timedelta(days=2)).isoformat(),
                'feedback': {'deleted': False, 'feedback': 'Супер!', 'feedback_type': 'positive'},
            },
            {
                'id': '8002',
                'item_id': '104005436',
                'invoice_state': 3,
                'date_pay': (self.now - timedelta(days=2)).isoformat(),
                'feedback': {'deleted': True, 'feedback': 'Удалён', 'feedback_type': 'positive'},
            },
            {
                'id': '8003',
                'item_id': '103376334',
                'invoice_state': 3,
                'date_pay': (self.now - timedelta(days=9)).isoformat(),
                'feedback': {'deleted': False, 'feedback': 'Старый заказ вне 7 дней', 'feedback_type': 'positive'},
            },
        ]
        reviews = [
            {'invoice_id': 8001, 'good': 104005409},
            {'invoice_id': 8002, 'good': 104005436},
            {'invoice_id': 8003, 'good': 103376334},
        ]

        first_day = self.engine.run_daily_review_schedule_if_due(lambda: (orders, reviews), now=self.now)
        same_day_repeat = self.engine.run_daily_review_schedule_if_due(lambda: (orders, reviews), now=self.now + timedelta(hours=3))
        next_day = self.engine.run_daily_review_schedule_if_due(lambda: (orders, reviews), now=self.now + timedelta(days=1))

        self.assertEqual(first_day['sent'], ['8001'])
        self.assertIsNone(same_day_repeat)
        self.assertEqual(next_day['sent'], [])

        msgs_8001 = self.chat.list_messages('8001')
        self.assertEqual(len(msgs_8001), 1)
        self.assertIn('AZAZAOUHCLAUDE', msgs_8001[0]['message'])
        self.assertEqual(self.chat.list_messages('8002'), [])
        self.assertEqual(self.chat.list_messages('8003'), [])

    def test_live_supplier_client_blocks_purchases_when_disabled(self):
        client = RoboticVNSupplierClient('dummy_key', allow_live_purchases=False)
        with self.assertRaises(RuntimeError):
            client.create_order('variant_01M60E6PGWFM88HSH1ZS1X1H1Q')

    def test_full_dry_run_suite(self):
        summary = run_dry_run_verification()
        self.assertEqual(summary['total_supplier_orders_created'], 2)
        self.assertEqual(summary['order_900001_total_coupons'], 1)


if __name__ == '__main__':
    unittest.main()
