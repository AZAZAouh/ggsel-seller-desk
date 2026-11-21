"""CapCut auto-delivery, support trigger, and 7-day review coupon engine.

Real supplier purchases and live buyer chat writes stay hard-blocked unless
mode == 'live' and the corresponding feature config has enabled == True.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from review_rewards import MESSAGE as COUPON_MESSAGE, ReviewRewards

ROOT = Path(__file__).resolve().parent


def warsaw_tz():
    try:
        return ZoneInfo('Europe/Warsaw')
    except ZoneInfoNotFoundError:
        return None


def to_warsaw(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = warsaw_tz()
    if tz is not None:
        return dt.astimezone(tz)
    utc_dt = dt.astimezone(timezone.utc)
    year = utc_dt.year
    # EU DST: last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC
    mar31 = datetime(year, 3, 31, 1, 0, tzinfo=timezone.utc)
    dst_start = mar31 - timedelta(days=(mar31.weekday() + 1) % 7)
    oct31 = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
    dst_end = oct31 - timedelta(days=(oct31.weekday() + 1) % 7)
    offset = timedelta(hours=2 if dst_start <= utc_dt < dst_end else 1)
    return utc_dt.astimezone(timezone(offset))


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        tz = warsaw_tz()
        dt = dt.replace(tzinfo=tz or timezone(timedelta(hours=1)))
    return dt


def format_credentials(delivery: dict) -> str:
    account = (delivery.get('account') or '').strip()
    password = (delivery.get('password') or '').strip()
    extra = (delivery.get('additional_info') or '').strip()
    if not account or not password:
        raise ValueError('Supplier delivery is missing account or password')
    lines = [f'Email: {account}', f'Пароль: {password}']
    if extra:
        lines.append(f'Дополнительно: {extra}')
    return '\n'.join(lines)


def format_balance(balance: dict) -> str:
    if not balance:
        return 'недоступен'
    return ', '.join(f'{v} {k.upper()}' for k, v in balance.items())


class DryRunSupplierAdapter:
    """In-memory RoboticVN simulator supporting normal purchases and post-send timeouts."""

    def __init__(self, initial_usd: float = 7.86, unit_prices: dict[str, float] | None = None):
        self.balance = {'vnd': 0, 'usd': round(initial_usd, 2)}
        self.unit_prices = unit_prices or {
            'variant_01M60E6PGWFM88HSH1ZS1X1H1Q': 0.25,
            'variant_01KSKHJGS2Q8T7VQ7T2K59VGZG': 1.04,
        }
        self.orders: list[dict] = []
        self.deliveries: dict[str, dict] = {}
        self.create_calls = 0
        self.fail_next_create_after_commit = False
        self.fail_next_list_orders = False

    def list_orders(self, limit: int = 50) -> list[dict]:
        if self.fail_next_list_orders:
            self.fail_next_list_orders = False
            raise TimeoutError('Simulated supplier list_orders timeout')
        return list(reversed(self.orders[-limit:]))

    def get_order(self, supplier_order_id: str) -> dict:
        for order in self.orders:
            if order['id'] == supplier_order_id:
                return order
        raise KeyError(f'Unknown supplier order {supplier_order_id}')

    def create_order(self, variant_id: str, quantity: int = 1, currency_code: str = 'usd') -> dict:
        self.create_calls += 1
        price = self.unit_prices.get(variant_id, 1.0)
        total = round(price * quantity, 2)
        if self.balance.get(currency_code, 0) < total:
            raise RuntimeError('Insufficient simulated supplier balance')
        self.balance[currency_code] = round(self.balance[currency_code] - total, 2)
        idx = len(self.orders) + 1
        oid = f'dry_sup_ord_{idx:04d}'
        now_iso = datetime.now(timezone.utc).isoformat()
        order = {
            'id': oid,
            'display_id': 1000 + idx,
            'status': 'completed',
            'payment_status': 'captured',
            'total': total,
            'currency_code': currency_code,
            'created_at': now_iso,
            'created_ts': time.time(),
            'items': [{'id': f'item_{idx}', 'variant_id': variant_id, 'quantity': quantity, 'unit_price': price}],
        }
        self.orders.append(order)
        self.deliveries[oid] = {
            'account': f'capcut.dryrun.{idx}@example.test',
            'password': f'DryRunPass#{idx:04d}',
            'additional_info': None,
        }
        if self.fail_next_create_after_commit:
            self.fail_next_create_after_commit = False
            raise TimeoutError('Simulated timeout after supplier committed order')
        return {'order_id': oid, 'status': 'completed'}

    def get_delivery(self, supplier_order_id: str) -> dict:
        if supplier_order_id not in self.deliveries:
            raise KeyError(f'No delivery for {supplier_order_id}')
        return dict(self.deliveries[supplier_order_id])

    def get_balance(self) -> dict:
        return dict(self.balance)


class DryRunChatAdapter:
    """In-memory GGsel debates/v2 simulator."""

    def __init__(self, image_supported: bool = True):
        self.image_supported = image_supported
        self.messages: dict[str, list[dict]] = {}
        self._seq = 10000
        self.fail_on_step_text: str | None = None

    def supports_image(self) -> bool:
        return self.image_supported

    def list_messages(self, order_id: str) -> list[dict]:
        return list(self.messages.get(str(order_id), []))

    def send_text(self, order_id: str, text: str) -> str:
        if self.fail_on_step_text and self.fail_on_step_text in text:
            self.fail_on_step_text = None
            raise TimeoutError('Simulated chat send timeout')
        self._seq += 1
        mid = str(self._seq)
        # Matches GGsel live debates/v2 quirk: seller messages have buyer=0, seller=0
        self.messages.setdefault(str(order_id), []).append(
            {
                'id': int(mid),
                'message': text,
                'buyer': 0,
                'seller': 0,
                'deleted': None,
                'date_written': datetime.now(timezone.utc).isoformat(),
                'is_img': 0,
                'filename': None,
            }
        )
        return f'dry_msg_{mid}'

    def send_image(self, order_id: str, image_path: Path) -> str:
        if not self.image_supported:
            raise RuntimeError('Image upload transport is not enabled')
        if not image_path.is_file():
            raise FileNotFoundError(str(image_path))
        self._seq += 1
        mid = str(self._seq)
        self.messages.setdefault(str(order_id), []).append(
            {
                'id': int(mid),
                'message': '',
                'buyer': 0,
                'seller': 0,
                'deleted': None,
                'date_written': datetime.now(timezone.utc).isoformat(),
                'is_img': 1,
                'filename': image_path.name,
            }
        )
        return f'dry_img_{mid}'

    def inject_buyer_message(self, order_id: str, text: str, message_id: int | None = None) -> int:
        if message_id is None:
            self._seq += 1
            message_id = self._seq
        # Matches GGsel live debates/v2 quirk: buyer messages return buyer=1 AND seller=1
        self.messages.setdefault(str(order_id), []).append(
            {
                'id': int(message_id),
                'message': text,
                'buyer': 1,
                'seller': 1,
                'deleted': None,
                'date_written': datetime.now(timezone.utc).isoformat(),
                'is_img': 0,
                'filename': None,
            }
        )
        return int(message_id)


class RoboticVNSupplierClient:
    """Live RoboticVN V2 adapter with hard purchase lock unless allow_live_purchases=True."""

    def __init__(self, api_key: str, allow_live_purchases: bool = False):
        self.api_key = api_key
        self.allow_live_purchases = allow_live_purchases

    def _call(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        sep = '&' if '?' in path else '?'
        url = f'https://api.roboticvn.com/api/v2/{path}{sep}locale=en-US'
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'AZAZAggselBot/0.2',
                'x-api-key': self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def list_orders(self, limit: int = 50) -> list[dict]:
        return self._call(f'orders?limit={int(limit)}&offset=0').get('data', [])

    def get_order(self, supplier_order_id: str) -> dict:
        return self._call(f'orders/{supplier_order_id}')['data']

    def create_order(self, variant_id: str, quantity: int = 1, currency_code: str = 'usd') -> dict:
        if not self.allow_live_purchases:
            raise RuntimeError('Live RoboticVN purchases are disabled by configuration')
        body = {
            'items': [{'variant_id': variant_id, 'quantity': int(quantity)}],
            'currency_code': currency_code,
            'payment_method': 'wallet',
        }
        return self._call('orders', payload=body)['data']

    def get_delivery(self, supplier_order_id: str) -> dict:
        raw = self._call(f'orders/{supplier_order_id}/delivery')
        body = raw.get('data', raw)
        items = body.get('delivered_accounts') or body.get('deliveredAccount') or []
        if not items:
            raise RuntimeError('Supplier order has no delivered credentials yet')
        return items[0]

    def get_balance(self) -> dict:
        return self._call('wallet/balance')['data']


class GGselChatClient:
    """GGsel Seller API V1 chat & review client.

    Note: Seller API V1 documents text-only `POST /api_sellers/api/debates/v2`
    (`create-message-without-file`); image upload is not yet exposed via API key,
    so `supports_image()` returns False until an official attachment transport is confirmed.
    """

    def __init__(self, seller_id: str | int, api_key: str, allow_live_messages: bool = False, http_fn=None):
        self.seller_id = int(seller_id)
        self.api_key = api_key
        self.allow_live_messages = allow_live_messages
        self._http = http_fn
        self._token: str | None = None
        self._token_at: float = 0.0

    def _request(self, url: str, payload: dict | None = None, headers: dict | None = None):
        if self._http is not None:
            return self._http(url, payload=payload, headers=headers)
        from sync_data import request as curl_request
        return curl_request(url, payload=payload, headers=headers)

    def token(self) -> str:
        if self._token and (time.monotonic() - self._token_at) < 900:
            return self._token
        stamp = str(int(time.time()))
        sign = hashlib.sha256((self.api_key + stamp).encode()).hexdigest()
        res = self._request(
            'https://seller.ggsel.com/api_sellers/api/apilogin',
            {'seller_id': self.seller_id, 'timestamp': stamp, 'sign': sign},
        )
        if not res.get('token'):
            raise RuntimeError('GGsel authentication failed')
        self._token = res['token']
        self._token_at = time.monotonic()
        return self._token

    def supports_image(self) -> bool:
        return False

    def support_chats(self):
        seen = set()
        page = 1
        while True:
            query = urlencode({'token': self.token(), 'page': page, 'count': 100})
            result = self._request('https://seller.ggsel.com/api_sellers/api/debates/v2/chats?' + query, headers={'locale': 'ru'})
            fresh = False
            for chat in result['items']:
                oid = str(chat.get('id_i'))
                if not oid.isdecimal() or oid in seen:
                    continue
                fresh = True
                seen.add(oid)
                yield chat
            if not fresh or len(result['items']) < 100:
                return
            if page >= int(result.get('cnt_pages') or 1):
                return
            page += 1

    def list_messages(self, order_id: str) -> list[dict]:
        url = 'https://seller.ggsel.com/api_sellers/api/debates/v2?' + urlencode(
            {'token': self.token(), 'id_i': int(order_id), 'count': 100}
        )
        res = self._request(url, headers={'locale': 'ru'})
        return res if isinstance(res, list) else []

    def send_text(self, order_id: str, text: str) -> str:
        if not self.allow_live_messages:
            raise RuntimeError('Live GGsel chat messages are disabled by configuration')
        url = 'https://seller.ggsel.com/api_sellers/api/debates/v2?' + urlencode(
            {'token': self.token(), 'id_i': int(order_id)}
        )
        self._request(url, payload={'message': text}, headers={'locale': 'ru'})
        # Confirm message ID from chat history
        for msg in reversed(self.list_messages(order_id)):
            if int(msg.get('buyer') or 0) == 0 and not msg.get('deleted') and (msg.get('message') or '').strip() == text.strip():
                return str(msg['id'])
        raise RuntimeError('GGsel message not confirmed in chat history')

    def send_image(self, order_id: str, image_path: Path) -> str:
        raise RuntimeError('GGsel chat supports text delivery only')

    def list_reviews(self, product_id: str | int, page: int = 1, count: int = 50) -> list[dict]:
        url = 'https://seller.ggsel.com/api_sellers/api/reviews?' + urlencode(
            {'token': self.token(), 'type': 'all', 'page': int(page), 'count': int(count), 'product_id': int(product_id)}
        )
        res = self._request(url, headers={'locale': 'ru-RU'})
        if res.get('retval', 0) != 0:
            raise RuntimeError('GGsel reviews error: ' + str(res.get('retval')))
        return res.get('reviews') or []

    def get_order_info(self, order_id: str | int) -> dict:
        url = f'https://seller.ggsel.com/api_sellers/api/purchase/info/{int(order_id)}?' + urlencode({'token': self.token()})
        res = self._request(url, headers={'locale': 'ru'})
        if res.get('retval', 0) != 0:
            raise RuntimeError('GGsel order info error: ' + str(res.get('retval')))
        return res.get('content') or {}


class CapCutCoordinator:
    """Durable state machine for CapCut orders, support alerts, and 7-day review coupons."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        supplier,
        chat,
        notify_owner,
        root: Path = ROOT,
        mode_override: str | None = None,
        progress=None,
    ):
        self.db = connection
        self.supplier = supplier
        self.chat = chat
        self.progress = progress
        self.notify_owner = notify_owner
        self.root = Path(root)

        products_cfg = json.loads((self.root / 'config/products.json').read_text('utf-8'))
        self.delivery_cfg = json.loads((self.root / 'config/capcut_delivery.json').read_text('utf-8'))
        self.coupon_cfg = json.loads((self.root / 'config/review_coupon.json').read_text('utf-8'))

        self.mode = mode_override or products_cfg.get('mode', 'dry_run')
        self.products = {str(p['ggsel_product_id']): p for p in products_cfg['products']}
        self.steps_spec = self.delivery_cfg['steps']
        self.support_spec = self.delivery_cfg['support']
        self.trigger_re = re.compile(
            r'(?<!\w)' + '(?:' + '|'.join(map(re.escape, [self.support_spec['trigger_word'], *self.support_spec.get('aliases', [])])) + ')' + r'(?!\w)',
            0 if self.support_spec.get('case_sensitive') else re.IGNORECASE,
        )

        self._init_schema()
        self.review_rewards = ReviewRewards(self.db)

    def _init_schema(self):
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS capcut_orders (
                    order_id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    supplier_variant_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stopped_step TEXT,
                    known_supplier_orders TEXT,
                    purchase_started_at REAL,
                    supplier_order_id TEXT UNIQUE,
                    credentials_json TEXT,
                    owner_notified TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )'''
            )
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS capcut_delivery_steps (
                    order_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message_id TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (order_id, step_id)
                )'''
            )
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS support_alerts (
                    buyer_message_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    notified_at REAL NOT NULL
                )'''
            )

    def get_state(self, key: str, default=None):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put_state(self, key: str, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (key, json.dumps(value)))

    def is_sync_enabled(self, product_id: str | int) -> bool:
        pid = str(product_id)
        cfg = self.products.get(pid)
        return bool(self.get_state('sync:' + pid, cfg['sync_enabled'] if cfg else False))

    def set_sync_enabled(self, product_id: str | int, enabled: bool):
        pid = str(product_id)
        if pid not in self.products:
            raise KeyError(f'Unconfigured CapCut product {pid}')
        self.put_state('sync:' + pid, bool(enabled))

    def is_delivery_enabled(self, product_id: str | int) -> bool:
        pid = str(product_id)
        cfg = self.products.get(pid)
        return bool(self.get_state('delivery:' + pid, cfg['delivery_enabled'] if cfg else False))

    def set_delivery_enabled(self, product_id: str | int, enabled: bool):
        pid = str(product_id)
        if pid not in self.products:
            raise KeyError(f'Unconfigured CapCut product {pid}')
        self.put_state('delivery:' + pid, bool(enabled))

    def _progress(self, oid, percent, stage, order=None):
        if self.progress is None:
            return
        try:
            self.progress(oid, percent, stage, order)
        except Exception as exc:
            print('Telegram order card update failed', oid, type(exc).__name__, flush=True)

    def _notify_once(self, order_id: str, token: str, message: str):
        row = self.db.execute('SELECT owner_notified FROM capcut_orders WHERE order_id=?', (order_id,)).fetchone()
        if row and row[0] == token:
            return
        if self.progress:
            self._progress(order_id, 100 if token == 'completed' else None, message)
        else:
            self.notify_owner(message)
        with self.db:
            self.db.execute(
                'UPDATE capcut_orders SET owner_notified=?, updated_at=? WHERE order_id=?',
                (token, time.time(), order_id),
            )

    def _record_precheck_stop(self, order_id: str, product: dict, step_name: str, reason: str) -> dict:
        now = time.time()
        with self.db:
            self.db.execute(
                '''INSERT OR IGNORE INTO capcut_orders (
                    order_id, product_id, supplier_variant_id, mode, status, stopped_step,
                    known_supplier_orders, purchase_started_at, supplier_order_id,
                    credentials_json, owner_notified, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?)''',
                (order_id, product['ggsel_product_id'], product['supplier_variant_id'], self.mode, 'precheck_failed', step_name, now, now),
            )
            self.db.execute(
                "UPDATE capcut_orders SET status='precheck_failed', stopped_step=?, updated_at=? WHERE order_id=? AND supplier_order_id IS NULL",
                (step_name, now, order_id),
            )
        prefix = '[DRY RUN] ' if self.mode != 'live' else ''
        self._notify_once(
            order_id,
            f'fail:{step_name}',
            f'{prefix}Ошибка выдачи заказа № {order_id} ({product["label"]}). Остановка на шаге: {step_name} ({reason}). Закупка не выполнялась.',
        )
        return {'action': 'stopped', 'order_id': order_id, 'step': step_name, 'reason': reason}

    def process_order(self, order: dict) -> dict:
        """Process a GGsel order safely and idempotently."""
        oid = str(order.get('id') or order.get('invoice_id') or '').strip()
        if not oid:
            raise ValueError('Order ID is required')
        pid = str(order.get('item_id') or '').strip()
        if pid not in self.products:
            return {'action': 'ignored_product', 'order_id': oid}

        if int(order.get('invoice_state') or 0) != 3:
            return {'action': 'ignored_state', 'order_id': oid}

        existing = self.db.execute(
            'SELECT status, supplier_order_id, credentials_json, stopped_step FROM capcut_orders WHERE order_id=?',
            (oid,),
        ).fetchone()

        if existing and existing[0] == 'completed':
            return {'action': 'already_completed', 'order_id': oid}

        product = self.products[pid]

        # Only check per-card switch before an order has claimed a purchase.
        if existing is None or (existing[0] == 'precheck_failed' and existing[1] is None):
            if not self.is_delivery_enabled(pid):
                return {'action': 'card_disabled', 'order_id': oid, 'product_id': pid}

            if self.mode == 'live' and not self.delivery_cfg.get('enabled', False):
                return {'action': 'global_disabled', 'order_id': oid}

            self._progress(oid, 0, "Проверяем заказ", order)
            try:
                qty = float(order.get('cnt_goods') or 1)
            except (TypeError, ValueError):
                qty = 0
            if qty != 1.0:
                return self._record_precheck_stop(oid, product, 'precheck_quantity', f'cnt_goods={order.get("cnt_goods")}')

            for step in self.steps_spec:
                if step['type'] == 'image' and step.get('required', True):
                    asset = self.root / step['asset_path']
                    if not asset.is_file():
                        return self._record_precheck_stop(oid, product, 'precheck_screenshot_asset', 'файл скриншота не найден')
                    if not self.chat.supports_image():
                        return self._record_precheck_stop(
                            oid,
                            product,
                            'precheck_image_transport',
                            'отправка изображений в API чатов GGsel ещё не подтверждена',
                        )

        # Step 1: Ensure order_id is durably persisted BEFORE any supplier purchase call.
        if existing is None or (existing[0] == 'precheck_failed' and existing[1] is None):
            try:
                known_ids = [str(o['id']) for o in self.supplier.list_orders(limit=50)]
            except Exception:
                return self._record_precheck_stop(oid, product, 'precheck_supplier_list', 'не удалось получить список заказов поставщика до закупки')

            now = time.time()
            with self.db:
                if existing is None:
                    self.db.execute(
                        '''INSERT INTO capcut_orders (
                            order_id, product_id, supplier_variant_id, mode, status, stopped_step,
                            known_supplier_orders, purchase_started_at, supplier_order_id,
                            credentials_json, owner_notified, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'purchasing', NULL, ?, ?, NULL, NULL, NULL, ?, ?)''',
                        (oid, pid, product['supplier_variant_id'], self.mode, json.dumps(known_ids), now, now, now),
                    )
                else:
                    self.db.execute(
                        '''UPDATE capcut_orders
                           SET status='purchasing', stopped_step=NULL, known_supplier_orders=?, purchase_started_at=?, updated_at=?
                           WHERE order_id=? AND supplier_order_id IS NULL''',
                        (json.dumps(known_ids), now, now, oid),
                    )
                for idx, step in enumerate(self.steps_spec):
                    self.db.execute(
                        'INSERT OR IGNORE INTO capcut_delivery_steps VALUES (?, ?, ?, ?, NULL, ?)',
                        (oid, idx, step['id'], 'pending', now),
                    )

            # Perform the single purchase request for this order.
            try:
                created = self.supplier.create_order(
                    product['supplier_variant_id'],
                    quantity=1,
                    currency_code='usd',
                )
                sup_id = str(created['order_id'])
                creds = self.supplier.get_delivery(sup_id)
                with self.db:
                    self.db.execute(
                        '''UPDATE capcut_orders
                           SET status='delivering', stopped_step=NULL, supplier_order_id=?, credentials_json=?, updated_at=?
                           WHERE order_id=?''',
                        (sup_id, json.dumps(creds, ensure_ascii=False), time.time(), oid),
                    )
            except Exception:
                with self.db:
                    self.db.execute(
                        "UPDATE capcut_orders SET status='purchase_uncertain', stopped_step='supplier_purchase', updated_at=? WHERE order_id=? AND supplier_order_id IS NULL",
                        (time.time(), oid),
                    )
                prefix = '[DRY RUN] ' if self.mode != 'live' else ''
                self._notify_once(
                    oid,
                    'fail:supplier_purchase',
                    f'{prefix}Неудача выдачи заказа № {oid} ({product["label"]}). Таймаут на шаге: supplier_purchase. При повторной обработке сначала выполнится сверка у поставщика без второй закупки.',
                )
                return {'action': 'purchase_uncertain', 'order_id': oid, 'step': 'supplier_purchase'}

        else:
            status, sup_id, creds_json, _ = existing
            if status in ('purchasing', 'purchase_uncertain') and not sup_id:
                rec = self._reconcile_or_halt_purchase(oid, product)
                if rec.get('action') != 'reconciled_and_completed':
                    return rec
                return rec
            if status == 'failed':
                return {'action': 'already_failed', 'order_id': oid, 'step': existing[3]}
            if sup_id and not creds_json:
                try:
                    creds = self.supplier.get_delivery(sup_id)
                    with self.db:
                        self.db.execute(
                            "UPDATE capcut_orders SET status='delivering', credentials_json=?, updated_at=? WHERE order_id=?",
                            (json.dumps(creds, ensure_ascii=False), time.time(), oid),
                        )
                except Exception:
                    return self._halt_step(oid, product, 'supplier_delivery_fetch')

        return self._deliver_steps(oid, product)

    def _reconcile_or_halt_purchase(self, order_id: str, product: dict) -> dict:
        row = self.db.execute(
            'SELECT known_supplier_orders, purchase_started_at, supplier_variant_id FROM capcut_orders WHERE order_id=?',
            (order_id,),
        ).fetchone()
        known_ids = set(json.loads(row[0] or '[]'))
        started_at = float(row[1] or 0.0)
        expected_variant = row[2]

        try:
            recent = self.supplier.list_orders(limit=50)
        except Exception:
            prefix = '[DRY RUN] ' if self.mode != 'live' else ''
            self._notify_once(
                order_id,
                'fail:supplier_purchase',
                f'{prefix}Неудача выдачи заказа № {order_id} ({product["label"]}). Таймаут на шаге: supplier_purchase. Повторная закупка заблокирована до сверки с поставщиком.',
            )
            return {'action': 'purchase_uncertain', 'order_id': order_id, 'step': 'supplier_purchase'}

        already_bound = {
            r[0]
            for r in self.db.execute('SELECT supplier_order_id FROM capcut_orders WHERE supplier_order_id IS NOT NULL').fetchall()
        }

        matches = []
        for summary in recent:
            sid = str(summary.get('id') or '')
            if not sid or sid in known_ids or sid in already_bound:
                continue
            created_ts = summary.get('created_ts')
            if created_ts is None:
                dt = parse_iso_datetime(summary.get('created_at'))
                created_ts = dt.timestamp() if dt else started_at
            if started_at and created_ts < (started_at - 10):
                continue
            detail = self.supplier.get_order(sid)
            items = detail.get('items') or []
            if len(items) == 1 and items[0].get('variant_id') == expected_variant and int(items[0].get('quantity') or 1) == 1:
                matches.append(sid)

        if len(matches) == 1:
            sid = matches[0]
            try:
                creds = self.supplier.get_delivery(sid)
            except Exception:
                with self.db:
                    self.db.execute(
                        "UPDATE capcut_orders SET supplier_order_id=?, stopped_step='supplier_delivery_fetch', updated_at=? WHERE order_id=?",
                        (sid, time.time(), order_id),
                    )
                return self._halt_step(order_id, product, 'supplier_delivery_fetch')

            with self.db:
                self.db.execute(
                    '''UPDATE capcut_orders
                       SET status='delivering', stopped_step=NULL, supplier_order_id=?, credentials_json=?, updated_at=?
                       WHERE order_id=?''',
                    (sid, json.dumps(creds, ensure_ascii=False), time.time(), order_id),
                )
            res = self._deliver_steps(order_id, product)
            if res.get('action') == 'completed':
                res['action'] = 'reconciled_and_completed'
            return res

        # 0 or >1 ambiguous orders after timeout: never risk buying a second account automatically.
        with self.db:
            self.db.execute(
                "UPDATE capcut_orders SET status='failed', stopped_step='supplier_purchase_reconciliation', updated_at=? WHERE order_id=?",
                (time.time(), order_id),
            )
        return self._halt_step(order_id, product, 'supplier_purchase_reconciliation')

    def _halt_step(self, order_id: str, product: dict, step_name: str) -> dict:
        with self.db:
            self.db.execute(
                'UPDATE capcut_orders SET stopped_step=?, updated_at=? WHERE order_id=?',
                (step_name, time.time(), order_id),
            )
        prefix = '[DRY RUN] ' if self.mode != 'live' else ''
        self._notify_once(
            order_id,
            f'fail:{step_name}',
            f'{prefix}Неудача выдачи заказа № {order_id} ({product["label"]}). Выдача остановлена на шаге: {step_name}.',
        )
        return {'action': 'failed_step', 'order_id': order_id, 'step': step_name}

    def _reconcile_step_in_chat(self, order_id: str, step: dict, creds: dict) -> str | None:
        history = self.chat.list_messages(order_id)
        seller_msgs = [m for m in history if int(m.get('buyer') or 0) == 0 and not m.get('deleted')]
        if step['type'] == 'image':
            for m in reversed(seller_msgs):
                if (int(m.get('is_img') or 0) == 1 and m.get('filename') == Path(step['asset_path']).name):
                    return str(m.get('id') or 'reconciled_img')
            return None
        expected_text = format_credentials(creds) if step['type'] == 'credentials' else step['text']
        for m in reversed(seller_msgs):
            if (m.get('message') or '').strip() == expected_text.strip():
                return str(m.get('id') or 'reconciled_msg')
        return None

    def _deliver_steps(self, order_id: str, product: dict) -> dict:
        row = self.db.execute('SELECT credentials_json FROM capcut_orders WHERE order_id=?', (order_id,)).fetchone()
        creds = json.loads(row[0])

        stages = {'account': 'Отправляем данные аккаунта', 'login_email': 'Отправляем инструкцию для телефона',
                  'login_instruction': 'Отправляем инструкцию для ПК', 'support_instruction': 'Отправляем подсказку о помощи',
                  'review_request': 'Отправляем просьбу об отзыве'}
        for idx, step in enumerate(self.steps_spec):
            step_id = step['id']
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO capcut_delivery_steps VALUES (?, ?, ?, ?, NULL, ?)',
                                (order_id, idx, step_id, 'pending', time.time()))
            srow = self.db.execute(
                'SELECT state, message_id FROM capcut_delivery_steps WHERE order_id=? AND step_id=?',
                (order_id, step_id),
            ).fetchone()
            state = srow[0] if srow else 'pending'
            if state == 'sent':
                continue

            self._progress(order_id, 30 + idx * 15, stages.get(step_id, 'Отправляем инструкцию'))
            if state in ('sending', 'unknown'):
                try:
                    found_id = self._reconcile_step_in_chat(order_id, step, creds)
                except Exception:
                    return self._halt_step(order_id, product, step_id)
                if found_id:
                    with self.db:
                        self.db.execute(
                            "UPDATE capcut_delivery_steps SET state='sent', message_id=?, updated_at=? WHERE order_id=? AND step_id=?",
                            (found_id, time.time(), order_id, step_id),
                        )
                    continue
                with self.db:
                    self.db.execute(
                        "UPDATE capcut_delivery_steps SET state='pending', updated_at=? WHERE order_id=? AND step_id=?",
                        (time.time(), order_id, step_id),
                    )

            with self.db:
                self.db.execute(
                    "UPDATE capcut_delivery_steps SET state='sending', updated_at=? WHERE order_id=? AND step_id=?",
                    (time.time(), order_id, step_id),
                )

            try:
                if step['type'] == 'credentials':
                    receipt = self.chat.send_text(order_id, format_credentials(creds))
                elif step['type'] == 'image':
                    receipt = self.chat.send_image(order_id, self.root / step['asset_path'])
                elif step['type'] == 'text':
                    receipt = self.chat.send_text(order_id, step['text'])
                else:
                    raise ValueError('Unsupported delivery step type: ' + str(step['type']))
                if not receipt:
                    raise RuntimeError('Empty chat message receipt')
            except Exception:
                with self.db:
                    self.db.execute(
                        "UPDATE capcut_delivery_steps SET state='unknown', updated_at=? WHERE order_id=? AND step_id=?",
                        (time.time(), order_id, step_id),
                    )
                return self._halt_step(order_id, product, step_id)

            with self.db:
                self.db.execute(
                    "UPDATE capcut_delivery_steps SET state='sent', message_id=?, updated_at=? WHERE order_id=? AND step_id=?",
                    (str(receipt), time.time(), order_id, step_id),
                )

        with self.db:
            self.db.execute(
                "UPDATE capcut_orders SET status='completed', stopped_step=NULL, updated_at=? WHERE order_id=?",
                (time.time(), order_id),
            )

        try:
            balance_text = format_balance(self.supplier.get_balance())
        except Exception:
            balance_text = 'не удалось обновить'

        prefix = '[DRY RUN] ' if self.mode != 'live' else ''
        self._notify_once(
            order_id,
            'completed',
            f'{prefix}Выдача завершена: заказ № {order_id} ({product["label"]}) — отправлены все 5 шагов.\nАктуальный баланс RoboticVN: {balance_text}',
        )
        return {'action': 'completed', 'order_id': order_id}

    def scan_buyer_messages(self, order_id: str | int, product_name: str | None = None, chat_url: str | None = None, since: float | None = None) -> list[str]:
        """Notify owner on buyer-only messages containing whole word «проблема»."""
        oid = str(order_id)
        messages = self.chat.list_messages(oid)
        row = self.db.execute('SELECT status, product_id, stopped_step FROM capcut_orders WHERE order_id=?', (oid,)).fetchone()
        if row:
            delivery_state = row[0] + (f' ({row[2]})' if row[2] else '')
            label = product_name or self.products.get(row[1], {}).get('label') or row[1]
        else:
            delivery_state = 'не в автовыдаче'
            label = product_name or 'Товар GGsel'

        alerted: list[str] = []
        for msg in messages:
            # GGsel live debates/v2 returns buyer=1, seller=1 for buyer messages and buyer=0, seller=0 for seller messages.
            if int(msg.get('buyer') or 0) != 1 or msg.get('deleted'):
                continue
            if since is not None:
                written = parse_iso_datetime(msg.get('date_written'))
                if written is None or written.timestamp() < since:
                    continue
            text = (msg.get('message') or '').strip()
            if not text or not self.trigger_re.search(text):
                continue
            mid = f'{oid}:{msg.get("id")}'
            if self.db.execute('SELECT 1 FROM support_alerts WHERE buyer_message_id=?', (mid,)).fetchone():
                continue
            self.notify_owner(f'🔔 Покупатель вызывает администратора\nЗаказ № {oid}\nТовар: {label}')
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO support_alerts VALUES (?, ?, ?)', (mid, oid, time.time()))
            alerted.append(mid)
        return alerted

    def check_recent_reviews(self, orders: list[dict], reviews: list[dict] | None = None, now: datetime | None = None) -> dict:
        """Check paid CapCut orders from the last 7 days (Europe/Warsaw) and send coupon once per order."""
        anchor = to_warsaw(now or datetime.now(timezone.utc))
        window_start = anchor - timedelta(days=int(self.coupon_cfg['schedule']['lookback_days']))
        allowed_products = set(str(x) for x in self.coupon_cfg['product_ids'])

        reviewed_invoice_ids = set()
        for rev in reviews or []:
            inv = rev.get('invoice_id')
            if inv is not None:
                reviewed_invoice_ids.add(str(int(inv)))

        sent_orders: list[str] = []
        observed_orders: list[str] = []

        for order in orders:
            oid = str(order.get('id') or order.get('invoice_id') or '').strip()
            pid = str(order.get('item_id') or '').strip()
            if not oid or pid not in allowed_products:
                continue
            if int(order.get('invoice_state') or 0) not in (3, 4):
                continue

            paid_dt = parse_iso_datetime(order.get('date_pay') or order.get('purchase_date'))
            if paid_dt is None:
                continue
            paid_warsaw = to_warsaw(paid_dt)
            if not (window_start <= paid_warsaw <= anchor):
                continue

            feedback = order.get('feedback')
            if feedback is not None:
                has_valid_review = bool(feedback) and not feedback.get('deleted')
            elif 'review_present' in order:
                has_valid_review = bool(order.get('review_present'))
            else:
                has_valid_review = oid in reviewed_invoice_ids

            if not has_valid_review:
                continue

            observed_orders.append(oid)
            self.review_rewards.observe(oid, oid, True)

            current = self.review_rewards.status(oid)
            if current and current['state'] in ('pending', 'unknown', 'sending'):
                history = self.chat.list_messages(oid)
                found_receipt = None
                for m in reversed(history):
                    if int(m.get('buyer') or 0) == 0 and not m.get('deleted') and 'AZAZAOUHCLAUDE' in (m.get('message') or ''):
                        found_receipt = str(m.get('id') or 'reconciled_coupon')
                        break
                if found_receipt:
                    self.review_rewards.reconcile(oid, found_receipt=found_receipt)
                    continue
                if current['state'] != 'pending':
                    continue  # Partial history cannot resolve an ambiguous previous send.

            if self.mode == 'live' and not self.coupon_cfg.get('enabled', False):
                continue

            if self.review_rewards.deliver(oid, lambda chat_id, msg: self.chat.send_text(chat_id, msg)):
                sent_orders.append(oid)

        return {'observed': observed_orders, 'sent': sent_orders, 'window_start': window_start.isoformat(), 'anchor': anchor.isoformat()}

    def run_daily_review_schedule_if_due(self, fetch_orders_and_reviews, now: datetime | None = None) -> dict | None:
        """Run the 00:00 Europe/Warsaw 7-day review scan once per Warsaw calendar day, catching up after downtime."""
        warsaw_now = to_warsaw(now or datetime.now(timezone.utc))
        today_key = warsaw_now.strftime('%Y-%m-%d')
        last_done = self.get_state('review_check:last_completed_date')
        if last_done is not None and last_done >= today_key:
            return None
        orders, reviews = fetch_orders_and_reviews()
        result = self.check_recent_reviews(orders, reviews=reviews, now=warsaw_now)
        self.put_state('review_check:last_completed_date', today_key)
        return result


def run_dry_run_verification() -> dict:
    """Execute end-to-end dry_run verification of all critical CapCut & coupon invariants."""
    db = sqlite3.connect(':memory:')
    supplier = DryRunSupplierAdapter(initial_usd=7.86)
    chat = DryRunChatAdapter(image_supported=True)
    notifications: list[str] = []

    engine = CapCutCoordinator(db, supplier, chat, notifications.append, mode_override='dry_run')
    # Enable 104005409 (weekly #1) and 103376334 (monthly), keep 104005436 (weekly #2) disabled!
    engine.set_delivery_enabled('104005409', True)
    engine.set_delivery_enabled('104005436', False)
    engine.set_delivery_enabled('103376334', True)

    now = datetime(2026, 11, 18, 0, 0, tzinfo=ZoneInfo('Europe/Warsaw'))
    paid_iso = (now - timedelta(days=1)).isoformat()

    # 1. New order on enabled weekly card 104005409
    order_new = {'id': '900001', 'item_id': '104005409', 'invoice_state': 3, 'cnt_goods': '1', 'date_pay': paid_iso}
    r_new = engine.process_order(order_new)

    # 2. Duplicate replay of the exact same order 900001
    r_dup = engine.process_order(order_new)

    # 3. Order on disabled second weekly card 104005436
    order_disabled = {'id': '900002', 'item_id': '104005436', 'invoice_state': 3, 'cnt_goods': '1', 'date_pay': paid_iso}
    r_disabled = engine.process_order(order_disabled)

    # 4. Supplier timeout AFTER purchase request was committed, then retry reconciles without second purchase
    supplier.fail_next_create_after_commit = True
    order_timeout = {'id': '900003', 'item_id': '103376334', 'invoice_state': 3, 'cnt_goods': '1', 'date_pay': paid_iso}
    r_timeout_first = engine.process_order(order_timeout)
    r_timeout_retry = engine.process_order(order_timeout)

    # 5. Buyer support word «проблема» + duplicate message check
    msg_id = chat.inject_buyer_message('900001', 'Здравствуйте, у меня проблема со входом!')
    alerts_first = engine.scan_buyer_messages('900001')
    alerts_second = engine.scan_buyer_messages('900001')

    # 6. Review check + repeated review check + deleted review check
    orders_with_reviews = [
        {**order_new, 'feedback': {'deleted': False, 'feedback': 'Отлично!', 'feedback_type': 'positive'}},
        {**order_timeout, 'feedback': {'deleted': True, 'feedback': 'Удалён', 'feedback_type': 'positive'}},
    ]
    reviews_feed = [{'invoice_id': 900001, 'good': 104005409}, {'invoice_id': 900003, 'good': 103376334}]
    rev_first = engine.check_recent_reviews(orders_with_reviews, reviews=reviews_feed, now=now)
    rev_second = engine.check_recent_reviews(orders_with_reviews, reviews=reviews_feed, now=now)

    coupon_msgs_900001 = [
        m for m in chat.list_messages('900001') if int(m.get('buyer') or 0) == 0 and 'AZAZAOUHCLAUDE' in (m.get('message') or '')
    ]
    coupon_msgs_900003 = [
        m for m in chat.list_messages('900003') if int(m.get('buyer') or 0) == 0 and 'AZAZAOUHCLAUDE' in (m.get('message') or '')
    ]

    summary = {
        'new_order': r_new['action'],
        'duplicate_order': r_dup['action'],
        'disabled_card': r_disabled['action'],
        'supplier_timeout_initial': r_timeout_first['action'],
        'supplier_timeout_reconciled': r_timeout_retry['action'],
        'total_supplier_create_calls': supplier.create_calls,
        'total_supplier_orders_created': len(supplier.orders),
        'order_900001_steps_sent': len([m for m in chat.list_messages('900001') if int(m.get('buyer') or 0) == 0]) - len(coupon_msgs_900001),
        'order_900003_steps_sent': len([m for m in chat.list_messages('900003') if int(m.get('buyer') or 0) == 0]),
        'support_alerts_first_scan': len(alerts_first),
        'support_alerts_repeat_scan': len(alerts_second),
        'review_coupons_first_run': rev_first['sent'],
        'review_coupons_second_run': rev_second['sent'],
        'order_900001_total_coupons': len(coupon_msgs_900001),
        'order_900003_deleted_review_coupons': len(coupon_msgs_900003),
        'ending_supplier_balance': supplier.get_balance(),
        'owner_notifications_count': len(notifications),
    }
    db.close()

    assert summary['new_order'] == 'completed'
    assert summary['duplicate_order'] == 'already_completed'
    assert summary['disabled_card'] == 'card_disabled'
    assert summary['supplier_timeout_initial'] == 'purchase_uncertain'
    assert summary['supplier_timeout_reconciled'] == 'reconciled_and_completed'
    assert summary['total_supplier_create_calls'] == 2  # 1 for 900001 + 1 for 900003; 0 for dup & disabled & retry!
    assert summary['total_supplier_orders_created'] == 2
    assert summary['order_900001_steps_sent'] == 5
    assert summary['order_900003_steps_sent'] == 5
    assert summary['support_alerts_first_scan'] == 1
    assert summary['support_alerts_repeat_scan'] == 0
    assert summary['review_coupons_first_run'] == ['900001']
    assert summary['review_coupons_second_run'] == []
    assert summary['order_900001_total_coupons'] == 1
    assert summary['order_900003_deleted_review_coupons'] == 0
    return summary


if __name__ == '__main__':
    print(json.dumps(run_dry_run_verification(), ensure_ascii=False, indent=2))
