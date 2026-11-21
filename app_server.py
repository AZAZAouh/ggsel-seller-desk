"""Loopback-only local app. Do not expose publicly without authentication."""
import json
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from decimal import Decimal, InvalidOperation
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from sync_data import sync

CODE_ROOT = Path(__file__).parent
ROOT = CODE_ROOT
PORT = 8766
CSRF = secrets.token_urlsafe(32)
LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
STATUS = {'syncing': False, 'error': None}


def read(name, default):
    p = ROOT / 'data' / name
    return json.loads(p.read_text('utf-8')) if p.exists() else default


def read_controls():
    cfg_path = (ROOT / 'config/products.json') if (ROOT / 'config/products.json').exists() else (CODE_ROOT / 'config/products.json')
    deliv_path = (ROOT / 'config/capcut_delivery.json') if (ROOT / 'config/capcut_delivery.json').exists() else (CODE_ROOT / 'config/capcut_delivery.json')
    doc = json.loads(cfg_path.read_text('utf-8')) if cfg_path.exists() else {'mode': 'dry_run', 'products': []}
    deliv_doc = json.loads(deliv_path.read_text('utf-8')) if deliv_path.exists() else {'enabled': False}
    db_path = ROOT / 'data/state.sqlite3'
    stored = {}
    if db_path.exists():
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            stored = {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM state WHERE key LIKE 'sync:%' OR key LIKE 'delivery:%'").fetchall()}
    cards = {}
    for p in doc.get('products', []):
        pid = str(p['ggsel_product_id'])
        cards[pid] = {
            'label': p['label'],
            'supplier_variant_id': p['supplier_variant_id'],
            'sync_enabled': bool(stored.get('sync:' + pid, p.get('sync_enabled', True))),
            'delivery_enabled': bool(stored.get('delivery:' + pid, p.get('delivery_enabled', False))),
        }
    mode = doc.get('mode', 'dry_run')
    return {'mode': mode, 'live_purchases_active': mode == 'live' and bool(deliv_doc.get('enabled')), 'cards': cards}


def write_card_control(product_id, sync_enabled=None, delivery_enabled=None):
    controls = read_controls()
    pid = str(product_id)
    if pid not in controls['cards']:
        raise ValueError('Unknown CapCut card')
    db_path = ROOT / 'data/state.sqlite3'
    db_path.parent.mkdir(exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            if sync_enabled is not None:
                conn.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', ('sync:' + pid, json.dumps(bool(sync_enabled))))
            if delivery_enabled is not None:
                conn.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', ('delivery:' + pid, json.dumps(bool(delivery_enabled))))


def refresh():
    if not SYNC_LOCK.acquire(blocking=False):
        return
    STATUS.update(syncing=True, error=None)
    try:
        sync()
    except Exception as e:
        STATUS['error'] = 'Не удалось обновить API (' + type(e).__name__ + '). Сохранён последний успешный снимок.'
    finally:
        STATUS['syncing'] = False
        SYNC_LOCK.release()


def dashboard_data():
    data = read('live.json', None)
    dates = read('office-holds.json', {})
    for order in (data or {}).get('orders', []):
        if order['id'] in dates and int(order.get('invoice_state') or 0) == 3:
            order.update(available_at=dates[order['id']], availability_source='ggsel_office')
    return data


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def trusted(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}', f'localhost:{PORT}']

    def end_headers(self):
        if not getattr(self, '_custom_cache', False):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def respond(self, data, status=200):
        self._custom_cache = True
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.trusted():
            return self.respond({'error': 'Forbidden'}, 403)
        if self.path == '/api/state':
            return self.respond(
                {
                    'data': dashboard_data(),
                    'settings': read('accounting.json', {'costs': {}, 'order_costs': {}, 'ads': []}),
                    'controls': read_controls(),
                    'status': STATUS,
                    'csrf': CSRF,
                }
            )
        if self.path.startswith('/api/'):
            return self.respond({'error': 'Not found'}, 404)
        return super().do_GET()

    def do_POST(self):
        if (
            not self.trusted()
            or self.headers.get('X-CSRF-Token') != CSRF
            or self.headers.get('Origin') not in [f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}']
        ):
            return self.respond({'error': 'Forbidden'}, 403)
        if self.path == '/api/refresh':
            threading.Thread(target=refresh, daemon=True).start()
            return self.respond({'ok': True}, 202)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < (1000000 if self.path == '/api/holds' else 10000):
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/holds':
                from datetime import datetime
                dates = body['dates']
                if not isinstance(dates, dict) or any(
                    not oid.isdecimal() or not isinstance(value, str) or 'T' not in value
                    or datetime.fromisoformat(value).tzinfo is None for oid, value in dates.items()
                ):
                    raise ValueError()
                with LOCK:
                    dest = ROOT / 'data/office-holds.json'
                    tmp = dest.with_suffix('.tmp')
                    tmp.write_text(json.dumps(dates), encoding='utf-8')
                    tmp.replace(dest)
                return self.respond({'ok': True})
            if self.path == '/api/card-control':
                if not isinstance(body.get('sync_enabled', True), bool) or not isinstance(body.get('delivery_enabled', True), bool):
                    raise ValueError()
                with LOCK:
                    write_card_control(
                        body['product_id'],
                        sync_enabled=body['sync_enabled'] if 'sync_enabled' in body else None,
                        delivery_enabled=body['delivery_enabled'] if 'delivery_enabled' in body else None,
                    )
                return self.respond({'ok': True})
            live = read('live.json', {'products': [], 'orders': []})
            pid = str(body['product_id'])
            if pid not in [str(p['id_goods']) for p in live['products']]:
                raise ValueError()
            amount = Decimal(str(body['amount']))
            if not amount.is_finite() or amount < 0 or amount > 10000000 or amount.as_tuple().exponent < -2:
                raise ValueError()
            currency = body['currency']
            if currency not in ['USD', 'RUB', 'EUR', 'VND']:
                raise ValueError()
            with LOCK:
                config = read('accounting.json', {'costs': {}, 'order_costs': {}, 'ads': []})
                if self.path == '/api/cost':
                    config['costs'][pid] = {'amount': str(amount), 'currency': currency, 'updated_at': time.time()}
                    if body.get('apply_missing') is True:
                        for order in live['orders']:
                            if str(order['item_id']) == pid and order['id'] not in config['order_costs']:
                                quantity = Decimal(str(order.get('cnt_goods') or '1'))
                                if quantity <= 0 or not quantity.is_finite():
                                    continue
                                config['order_costs'][order['id']] = {
                                    'amount': str(amount * quantity),
                                    'currency': currency,
                                    'source': 'manual',
                                    'saved_at': time.time(),
                                }
                elif self.path == '/api/ad':
                    from datetime import date
                    date.fromisoformat(body['date'])
                    config['ads'].append(
                        {'id': secrets.token_hex(8), 'product_id': pid, 'amount': str(amount), 'currency': currency, 'date': body['date']}
                    )
                else:
                    return self.respond({'error': 'Not found'}, 404)
                dest = ROOT / 'data/accounting.json'
                temp = dest.with_suffix('.tmp')
                temp.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
                temp.replace(dest)
            return self.respond({'ok': True})
        except (ValueError, KeyError, InvalidOperation):
            return self.respond({'error': 'Проверь товар, дату, сумму и валюту.'}, 400)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', PORT), partial(Handler, directory=str(CODE_ROOT / 'miniapp')))
    server.serve_forever()
