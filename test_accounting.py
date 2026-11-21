import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
import app_server as app


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_root,self.old_port=app.ROOT,app.PORT
        app.ROOT=Path(self.tmp.name);(app.ROOT/'data').mkdir()
        (app.ROOT/'data/live.json').write_text(json.dumps({'products':[{'id_goods':1}], 'orders':[
            {'id':'a','item_id':1,'cnt_goods':'2'}]}))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        app.PORT=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        app.ROOT,app.PORT=self.old_root,self.old_port;self.tmp.cleanup()

    def post(self,amount,apply=True,token=None):
        url=f'http://127.0.0.1:{app.PORT}'
        req=urllib.request.Request(url+'/api/cost',data=json.dumps({'product_id':'1','amount':amount,
            'currency':'USD','apply_missing':apply}).encode(),headers={
                'Origin':url,'X-CSRF-Token':token or app.CSRF,'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as r:return json.load(r)

    def test_quantity_and_no_historical_rewrite(self):
        self.post('1.25')
        self.post('9.00')
        state=app.read('accounting.json',{})
        self.assertEqual(state['order_costs']['a']['amount'],'2.50')
        self.assertEqual(state['costs']['1']['amount'],'9.00')

    def test_default_does_not_rewrite_orders(self):
        self.post('1.25',False)
        self.assertEqual(app.read('accounting.json',{})['order_costs'],{})

    def test_invalid_amounts(self):
        for amount in ['NaN','Infinity','-1','1.234']:
            with self.assertRaises(urllib.error.HTTPError) as error:self.post(amount)
            self.assertEqual(error.exception.code,400)

    def test_csrf(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.post('1',token='wrong')
        self.assertEqual(error.exception.code,403)

    def test_independent_capcut_card_controls(self):
        url=f'http://127.0.0.1:{app.PORT}'
        req=urllib.request.Request(url+'/api/card-control',data=json.dumps({'product_id':'104005409',
            'sync_enabled':False,'delivery_enabled':True}).encode(),headers={
                'Origin':url,'X-CSRF-Token':app.CSRF,'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as r:self.assertTrue(json.load(r)['ok'])
        with urllib.request.urlopen(url+'/api/state') as r:state=json.load(r)
        cards=state['controls']['cards']
        self.assertFalse(cards['104005409']['sync_enabled'])
        self.assertTrue(cards['104005409']['delivery_enabled'])
        self.assertTrue(cards['104005436']['sync_enabled'])
        self.assertFalse(cards['104005436']['delivery_enabled'])
        self.assertFalse(state['controls']['live_purchases_active'])
