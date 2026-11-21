import hashlib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from bot import settings

UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def request(url, payload=None, headers=None):
    config = [
        "url = " + json.dumps(url),
        "header = " + json.dumps("Accept: application/json"),
        "header = " + json.dumps("Content-Type: application/json"),
    ]
    for key, value in (headers or {}).items():
        config.append("header = " + json.dumps(key + ": " + value))
    if payload is not None:
        config.append("data = " + json.dumps(json.dumps(payload)))
    result = subprocess.run(
        ["curl", "-4", "-sS", "--fail", "--max-time", "15", "--config", "-"],
        input="\n".join(config),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError("API transport failed (curl " + str(result.returncode) + ")")
    if payload is not None and not result.stdout.strip() and url.split("?", 1)[0].endswith("/debates/v2"):
        return {}
    return json.loads(result.stdout)


def resolve_product_name(raw_name, sale_name, item_id, catalog_names):
    candidate = (raw_name or "").strip()
    if candidate and not UUID_RE.match(candidate):
        return candidate
    if sale_name and sale_name.strip():
        return sale_name.strip()
    try:
        mapped = catalog_names.get(int(item_id)) if item_id is not None else None
    except (TypeError, ValueError):
        mapped = None
    if mapped and mapped.strip():
        return mapped.strip()
    return candidate or None


ROOT = Path(__file__).parent


def sync():
    cfg = settings()
    stamp = str(int(time.time()))
    base = 'https://seller.ggsel.com/api_sellers/api/'
    auth = request(
        base + 'apilogin',
        {
            'seller_id': int(cfg['GGSEL_SELLER_ID']),
            'timestamp': stamp,
            'sign': hashlib.sha256((cfg['GGSEL_API_KEY'] + stamp).encode()).hexdigest(),
        },
    )
    if not auth.get('token'):
        raise RuntimeError('GGsel authentication failed: ' + str(auth.get('retval')))

    def gg(path, body=None, **params):
        result = request(base + path + '?' + urlencode({'token': auth['token'], **params}), body, {'locale': 'ru'})
        if result.get('retval', 0) != 0:
            raise RuntimeError('GGsel response: ' + str(result.get('retval')))
        return result

    print('Authenticated', flush=True)
    products = []
    seen = set()
    for page in range(1, 101):
        response = gg(
            'seller-goods',
            {'id_seller': int(cfg['GGSEL_SELLER_ID']), 'rows': 100, 'page': page, 'currency': 'USD', 'lang': 'ru-RU'},
            page=page,
            rows=100,
        )
        batch = response.get('rows', [])
        fresh = [p for p in batch if p['id_goods'] not in seen]
        if not fresh:
            break
        products.extend(fresh)
        seen.update(p['id_goods'] for p in fresh)
        print('Catalog page', page, 'new', len(fresh), flush=True)
        if page >= response.get('pages', 1):
            break
    print('Catalog read:', len(products), flush=True)
    catalog_names = {int(p['id_goods']): p.get('name_goods') for p in products if p.get('id_goods') is not None}

    sales = gg('seller-last-sales', top=1000, group='false').get('sales', [])
    print('Sales read:', len(sales), flush=True)

    cache_path = ROOT / 'data/order-cache.json'
    cache = json.loads(cache_path.read_text('utf-8')) if cache_path.exists() else {}
    errors = []

    def detail(sale):
        oid = str(sale['invoice_id'])
        sale_prod = sale.get('product') or {}
        sale_name = sale_prod.get('name')
        try:
            order = {}
            for attempt in range(3):
                try:
                    order = gg('purchase/info/' + oid).get('content', {})
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1.0 * (attempt + 1))
            safe = {
                k: order.get(k)
                for k in [
                    'item_id',
                    'name',
                    'amount',
                    'currency_type',
                    'invoice_state',
                    'purchase_date',
                    'date_pay',
                    'cnt_goods',
                    'day_lock',
                    'lock_state',
                    'profit',
                ]
            }
            if safe.get('item_id') is None and sale_prod.get('id') is not None:
                safe['item_id'] = sale_prod.get('id')
            safe['name'] = resolve_product_name(safe.get('name'), sale_name, safe.get('item_id'), catalog_names)
            safe.update(
                id=oid,
                review_present=bool(order.get('feedback') and not order['feedback'].get('deleted')),
                available_at=None,
                availability_source=None,
                fetched_at=time.time(),
                stale=False,
            )
            return oid, safe, None
        except Exception:
            cached = cache.get(oid)
            if cached:
                item_id = cached.get('item_id') or sale_prod.get('id')
                cached = {
                    **cached,
                    'item_id': item_id,
                    'name': resolve_product_name(cached.get('name'), sale_name, item_id, catalog_names),
                    'stale': True,
                }
            return oid, cached, 'Не обновлён заказ ' + oid

    with ThreadPoolExecutor(max_workers=3) as executor:
        for oid, safe, error in executor.map(detail, sales):
            if error:
                errors.append(error)
            if safe:
                cache[oid] = safe

    cache_path.parent.mkdir(exist_ok=True)
    cache_tmp = cache_path.with_suffix('.tmp')
    cache_tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    cache_tmp.replace(cache_path)

    orders = [cache[str(s['invoice_id'])] for s in sales if str(s['invoice_id']) in cache]
    confirmed_path = ROOT / 'config/confirmed_availability.json'
    confirmed = json.loads(confirmed_path.read_text('utf-8')) if confirmed_path.exists() else {}
    for order in orders:
        if order['id'] in confirmed:
            item = confirmed[order['id']]
            order.update(available_at=item['available_at'], availability_source=item['source'])
    print('Order details:', len(orders), 'errors:', len(errors), flush=True)

    headers = {'x-api-key': cfg['ROBOTICVN_API_KEY']}
    supplier_balance = request('https://api.roboticvn.com/api/v2/wallet/balance', headers=headers)['data']
    supplier = request('https://api.roboticvn.com/api/v2/products/prod_01KMJ36ZAT64RSNMTFATEKB0X5?locale=en-US', headers=headers)['data']
    output = {
        'updated_at': time.time(),
        'products': [
            {k: p.get(k) for k in ['id_goods', 'name_goods', 'price_usd', 'cnt_sell', 'cnt_return', 'visible']}
            for p in products
        ],
        'errors': errors,
        'orders': orders,
        'supplier_balance': supplier_balance,
        'supplier': supplier,
        'requested_limit': 1000,
        'received_sales': len(sales),
        'coverage': (
            'Загружено '
            + str(len(orders))
            + ' из '
            + str(len(sales))
            + ' полученных заказов. Ошибок обновления: '
            + str(len(errors))
            + '. Полнота истории не подтверждена площадкой.'
        ),
        'hold_note': 'Только статус «Оплачен». Ожидаем подтверждённое поле «Доступно» для каждого заказа; дату из срока холда не вычисляем.',
    }
    dest = ROOT / 'data/live.json'
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    tmp.replace(dest)
    print(json.dumps({'products': len(products), 'orders': len(orders), 'supplier_balance': supplier_balance}, ensure_ascii=False))
    return output


if __name__ == '__main__':
    sync()
