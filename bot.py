"""Private Telegram control panel for AZAZA GGsel store."""
import json
import os
import sqlite3
import time
import urllib.request
from pathlib import Path

from capcut_delivery import CapCutCoordinator, GGselChatClient, RoboticVNSupplierClient

ROOT = Path(__file__).resolve().parent


def settings():
    values = dict(os.environ)
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.startswith('#'):
            key, value = line.split('=', 1)
            values.setdefault(key.strip(), value.strip())
    return values


def request(url, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'AZAZAggselBot/0.2',
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


class Bot:
    def __init__(self, cfg, database=None):
        self.cfg = cfg
        (ROOT / 'data').mkdir(exist_ok=True)
        self.db = sqlite3.connect(database or ROOT / 'data/state.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        products_doc = json.loads((ROOT / 'config/products.json').read_text('utf-8'))
        self.mode = products_doc.get('mode', 'dry_run')
        self.products = products_doc['products']
        self.delivery_doc = json.loads((ROOT / 'config/capcut_delivery.json').read_text('utf-8'))
        self.coupon_doc = json.loads((ROOT / 'config/review_coupon.json').read_text('utf-8'))

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (key, json.dumps(value)))

    def tg(self, method, **payload):
        result = request('https://api.telegram.org/bot' + self.cfg['TELEGRAM_BOT_TOKEN'] + '/' + method, payload)
        if not result.get('ok'):
            raise RuntimeError('Telegram request rejected')
        return result['result']

    def notify_owner(self, text):
        self.tg('sendMessage', chat_id=int(self.cfg['TELEGRAM_OWNER_ID']), text=text)

    def order_progress(self, oid, percent, stage, order=None):
        key = 'telegram_card:' + oid
        card = self.get(key, {})
        if order:
            info = order.get('buyer_info') or {}
            card['buyer'] = str(info.get('email') or 'Не указан в GGsel')[:150]
            card['product'] = str(order.get('name') or next(
                (p['label'] for p in self.products if p['ggsel_product_id'] == str(order.get('item_id'))), 'CapCut'))[:250]
        value = card.get('percent', 0) if percent is None else percent
        status = 'ОСТАНОВЛЕНА' if percent is None else 'ЗАВЕРШЕНА' if percent == 100 else 'ЗАПУЩЕНА'
        blocks = value // 10
        text = (f"🛍 Новая покупка\n{card.get('product', 'CapCut')}\n"
                f"Покупатель: {card.get('buyer', 'Не указан в GGsel')}\nЗаказ № {oid}\n\n"
                f"Выдача: {status}\n{'▰' * blocks}{'▱' * (10 - blocks)}  {value}%\n{stage}")
        if card.get('text') == text:
            return
        args = {'chat_id': int(self.cfg['TELEGRAM_OWNER_ID']), 'text': text}
        if card.get('message_id'):
            self.tg('editMessageText', message_id=card['message_id'], **args)
        else:
            card['message_id'] = self.tg('sendMessage', **args)['message_id']
        card.update(text=text, percent=value)
        self.put(key, card)

    def supplier(self, path):
        return request(
            'https://api.roboticvn.com/api/v2/' + path + '?locale=en-US',
            headers={'x-api-key': self.cfg['ROBOTICVN_API_KEY']},
        )['data']

    def sync(self, product):
        data = self.supplier('products/' + product['supplier_product_id'])
        variant = next(v for v in data['variants'] if v['id'] == product['supplier_variant_id'])
        self.put('catalog:' + product['ggsel_product_id'], {'variant': variant, 'time': time.time()})

    def send(self, text, rows):
        self.tg(
            'sendMessage',
            chat_id=int(self.cfg['TELEGRAM_OWNER_ID']),
            text=text,
            reply_markup={'inline_keyboard': [[{'text': t, 'callback_data': c} for t, c in row] for row in rows]},
        )

    def live_purchases_active(self):
        return self.mode == 'live' and bool(self.delivery_doc.get('enabled'))

    def show(self, action='home'):
        back = [[('Главное меню', 'home')]]
        mode_line = (
            'Боевой режим закупок включён.'
            if self.live_purchases_active()
            else f'Режим: {self.mode} (реальные закупки выключены).'
        )
        if action == 'home':
            self.send(
                f'AZAZA · управление GGsel\n{mode_line}',
                [[('Товары CapCut', 'products')], [('Баланс поставщика', 'balance')], [('Статистика', 'stats')]],
            )
        elif action == 'products':
            self.send(
                'Выбери карточку GGsel:',
                [[(p['label'] + ' · ' + p['ggsel_product_id'], 'p:' + p['ggsel_product_id'])] for p in self.products] + back,
            )
        elif action == 'balance':
            balance = self.supplier('wallet/balance')
            self.send('Баланс поставщика сейчас:\n' + '\n'.join(f'{v} {k.upper()}' for k, v in balance.items()), back)
        elif action == 'stats':
            self.send(
                'Отчёты по периодам, зачислениям, расходам и календарю холда доступны в локальном Mini App (app_server.py).',
                back,
            )
        elif ':' in action:
            operation, pid = action.split(':', 1)
            p = next((p for p in self.products if p['ggsel_product_id'] == pid), None)
            if p is None:
                return
            sync_key = 'sync:' + pid
            deliv_key = 'delivery:' + pid
            if operation in ('on', 'off'):
                self.put(sync_key, operation == 'on')
            elif operation in ('deliv_on', 'deliv_off'):
                self.put(deliv_key, operation == 'deliv_on')
            elif operation == 'refresh':
                self.sync(p)
            elif operation == 'delivery':
                if not self.live_purchases_active():
                    self.send(
                        f'Реальные закупки сейчас недоступны ({mode_line})\nПереключатель карточки № {pid} можно подготовить отдельно кнопкой на экране товара.',
                        [[('К товару', 'p:' + pid)]],
                    )
                    return

            sync_enabled = self.get(sync_key, p['sync_enabled'])
            deliv_enabled = self.get(deliv_key, p['delivery_enabled'])
            cached = self.get('catalog:' + pid)
            deliv_status = 'включена' if deliv_enabled else 'выключена'
            if not self.live_purchases_active():
                deliv_status += ' (закупки глобально выключены)'
            text = (
                f"{p['label']} · {pid}\n"
                f"Синхронизация: {'включена' if sync_enabled else 'выключена'}\n"
                f"Автовыдача карточки: {deliv_status}"
            )
            if cached:
                v = cached['variant']
                stamp = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(cached['time']))
                text += f"\nЗакупка: {v['prices'].get('usd', '—')} USD\nОстаток: {v['available_quantity']}\nОбновлено: {stamp}"
            else:
                text += '\nКаталог ещё не обновлён.'
            self.send(
                text,
                [
                    [
                        (
                            'Отключить синхронизацию' if sync_enabled else 'Включить синхронизацию',
                            ('off:' if sync_enabled else 'on:') + pid,
                        )
                    ],
                    [
                        (
                            'Выключить выдачу карточки' if deliv_enabled else 'Включить выдачу карточки',
                            ('deliv_off:' if deliv_enabled else 'deliv_on:') + pid,
                        )
                    ],
                    [('Обновить сейчас', 'refresh:' + pid)],
                    [('Все товары', 'products')],
                ],
            )

    def handle(self, update):
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        sender = callback.get('from', {}) if callback else message.get('from', {})
        owner = int(self.cfg['TELEGRAM_OWNER_ID'])
        if sender.get('id') != owner or message.get('chat', {}).get('id') != owner:
            return
        if callback:
            self.tg('answerCallbackQuery', callback_query_id=callback['id'])
            self.show(callback.get('data', 'home'))
        else:
            self.show('home')

    def build_coordinator(self):
        live_buy = self.live_purchases_active()
        live_msg = live_buy or bool(self.coupon_doc.get('enabled'))
        sup = RoboticVNSupplierClient(self.cfg['ROBOTICVN_API_KEY'], allow_live_purchases=live_buy)
        chat = GGselChatClient(self.cfg['GGSEL_SELLER_ID'], self.cfg['GGSEL_API_KEY'], allow_live_messages=live_msg)
        return CapCutCoordinator(self.db, sup, chat, self.notify_owner, root=ROOT, progress=self.order_progress), chat

    def poll_store_events(self, coordinator, ggsel_client):
        started = self.get('support_started_at')
        if started is None:
            started = time.time()
            self.put('support_started_at', started)
        if self.live_purchases_active():
            activated = self.get('purchases_started_at')
            if activated is None:
                activated = time.time()
                self.put('purchases_started_at', activated)
            for order in self.recent_capcut_orders(ggsel_client, time.time() - activated):
                coordinator.process_order(order)
        else:
            if self.get('purchases_started_at') is not None:
                self.put('purchases_started_at', None)
        for chat in ggsel_client.support_chats():
            product = coordinator.products.get(str(chat.get('product')))
            if not product:
                continue
            oid = str(chat['id_i'])
            key = 'support_scan:' + oid
            stamp = [chat.get('last_message'), chat.get('cnt_msg')]
            if stamp[0] and self.get(key) == stamp:
                continue
            try:
                coordinator.scan_buyer_messages(oid, product['label'], since=started)
                self.put(key, stamp)
            except Exception as exc:
                print('Support scan failed for order', oid, type(exc).__name__, flush=True)
        if self.coupon_doc.get('enabled'):
            coordinator.run_daily_review_schedule_if_due(lambda: (self.recent_capcut_orders(ggsel_client, 7 * 86400), []))

    def recent_capcut_orders(self, client, seconds):
        from capcut_delivery import parse_iso_datetime
        from urllib.parse import urlencode
        url = 'https://seller.ggsel.com/api_sellers/api/seller-last-sales?' + urlencode(
            {'token': client.token(), 'top': 1000, 'group': 'false'})
        result = client._request(url, headers={'locale': 'ru'})
        products = {p['ggsel_product_id'] for p in self.products}
        cutoff = time.time() - seconds
        orders = []
        for sale in result['sales']:
            if str((sale.get('product') or {}).get('id')) not in products:
                continue
            stamp = parse_iso_datetime(sale.get('date'))
            if stamp and stamp.timestamp() < cutoff:
                continue
            oid = str(sale['invoice_id'])
            order = client.get_order_info(oid)
            paid = parse_iso_datetime(order.get('date_pay') or order.get('purchase_date'))
            if paid and paid.timestamp() >= cutoff:
                orders.append({**order, 'id': oid})
        return orders

    def run(self):
        me = self.tg('getMe')
        if me['username'].lower() != 'azazaggselbot':
            raise RuntimeError('Unexpected bot identity')
        if self.tg('getWebhookInfo').get('url'):
            raise RuntimeError('Existing webhook; polling not started')
        print('Bot verified; private polling started', flush=True)
        coordinator, ggsel_client = (
            self.build_coordinator()
            if self.cfg.get('GGSEL_API_KEY') and self.cfg.get('GGSEL_SELLER_ID') and self.cfg.get('ROBOTICVN_API_KEY')
            else (None, None)
        )
        last_sync = 0
        last_store_poll = 0
        while True:
            try:
                if time.monotonic() - last_sync > 300:
                    for p in self.products:
                        if self.get('sync:' + p['ggsel_product_id'], p['sync_enabled']):
                            try:
                                self.sync(p)
                            except Exception as exc:
                                print('Catalog sync failed: ' + type(exc).__name__, flush=True)
                    last_sync = time.monotonic()
                if coordinator and time.monotonic() - last_store_poll > 60:
                    try:
                        self.poll_store_events(coordinator, ggsel_client)
                    except Exception as exc:
                        print('Store poll failed: ' + type(exc).__name__, flush=True)
                    last_store_poll = time.monotonic()
                updates = self.tg(
                    'getUpdates',
                    offset=self.get('offset', 0),
                    timeout=20,
                    allowed_updates=['message', 'callback_query'],
                )
                for update in updates:
                    try:
                        self.handle(update)
                    except Exception as exc:
                        print('Update failed: ' + type(exc).__name__, flush=True)
                    self.put('offset', update['update_id'] + 1)
                self.put('heartbeat', time.time())
            except Exception as exc:
                print('Polling failed: ' + type(exc).__name__, flush=True)
                time.sleep(5)


if __name__ == '__main__':
    Bot(settings()).run()
