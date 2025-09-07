# core/session.py

import time
import json
import os
import logging
from core.broker import BrokerSession
from core.cmp import CMPManager
from core.utils import read_csv

class SessionCache:
    GTT_PLAN_CACHE_PATH = "data/gtt_plan_cache.json"

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self.last_refreshed = 0
        self.broker = BrokerSession()
        self.kite = self.broker.get_kite_session()
        self.holdings = []
        self.entry_levels = []
        self.gtt_symbols = set()
        self.cmp_manager = CMPManager(csv_path="data/Name-symbol-mapping.csv", ttl=ttl)
        self.refresh_all_caches()

    def is_stale(self) -> bool:
        return (time.time() - self.last_refreshed) > self.ttl

    def refresh_all_caches(self):
        #print("🔄 Refreshing all caches...")
        self.refresh_holdings()

        self.refresh_entry_levels()

        self.refresh_gtt_cache()
        # print("📂 holding: ")
        # print(self.holdings)
        # print("📂 Entry level: ")
        # print(self.entry_levels)
        # print("📂 GTT: ")
        # print(self.gtt_cache)
        self.refresh_cmp_cache()
        self.last_refreshed = time.time()

    def refresh_holdings(self):
        self.holdings = self.kite.holdings()

    def refresh_entry_levels(self):
        self.entry_levels = read_csv("data/entry_levels.csv")

    def refresh_gtt_cache(self):
        try:
            gtts = self.kite.get_gtts()
            self.gtt_cache = []
            for g in gtts:
                    self.gtt_cache.append({
                        'id': g.get('id'),
                        'created_at': g.get('created_at'),
                        'instrument_token': g.get('condition', {}).get('instrument_token'),
                        'tradingsymbol': g.get('condition', {}).get('tradingsymbol'),
                        'exchange': g.get('condition', {}).get('exchange'),
                        'trigger_values': g.get('condition', {}).get('trigger_values'),
                        'quantity': g.get('orders', [{}])[0].get('quantity'),
                        'transaction_type': g.get('orders', [{}])[0].get('transaction_type'),
                        'price': g.get('orders', [{}])[0].get('price'),
                        'status': g.get('status'),
                        'type': g.get('type')
                    })
        except Exception as e:
            print(f"❌ Failed to refresh GTT cache: {e}")
            self.gtt_cache = []


    def refresh_cmp_cache(self):
            gtts = self.kite.get_gtts()
            self.cmp_manager.refresh_cache(self.holdings, gtts, self.entry_levels)

    def get_gtt_cache(self):
        if self.is_stale():
            self.refresh_all_caches()
        return self.gtt_cache

    def get_existing_gtt_symbols(self):
        if self.is_stale():
            self.refresh_all_caches()
        return {
            g["tradingsymbol"].strip().upper()
            for g in self.gtt_cache
            if g["transaction_type"] == self.kite.TRANSACTION_TYPE_BUY
        }

    
    def get_holdings(self):
        if self.is_stale():
            self.refresh_all_caches()
        return self.holdings

    def get_entry_levels(self):
        if self.is_stale():
            self.refresh_all_caches()
        return self.entry_levels

    def get_cmp_manager(self):
        if self.is_stale():
            self.refresh_all_caches()
        return self.cmp_manager
    # ──────────────── GTT Plan Cache ──────────────── #
    def write_gtt_plan(self, orders: list):
        os.makedirs(os.path.dirname(self.GTT_PLAN_CACHE_PATH), exist_ok=True)
        try:
            with open(self.GTT_PLAN_CACHE_PATH, "w") as f:
                json.dump(orders, f, indent=2)
        except Exception as e:
            logging.error(f"❌ Failed to write GTT plan cache: {e}")

    def read_gtt_plan(self) -> list:
        if not os.path.exists(self.GTT_PLAN_CACHE_PATH):
            return []
        try:
            print("📂 Reading GTT plan from cache: ")  
            with open(self.GTT_PLAN_CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"❌ Failed to read GTT plan cache: {e}")
            return []

    def delete_gtt_plan(self):
        try:
            os.remove(self.GTT_PLAN_CACHE_PATH)
        except Exception as e:
            logging.warning(f"⚠️ Failed to delete GTT plan cache: {e}")