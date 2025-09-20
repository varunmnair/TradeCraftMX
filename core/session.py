# core/session.py

import time
import json
import os
import logging
from core.cmp import CMPManager
from core.utils import read_csv


class SessionCache:
    GTT_PLAN_CACHE_PATH = "data/gtt_plan_cache.json"

    def __init__(self, session_manager, ttl: int = 300):
        self.ttl = ttl
        self.last_refreshed = 0
        self.broker = None # Will be set from main_menu
        self.session_manager = session_manager # Store the session manager
        self.holdings = []
        self.entry_levels = []
        self.gtt_symbols = set()
        self.cmp_manager = None # Initialize lazily
        self.gtt_cache = []

    def is_stale(self) -> bool:
        return (time.time() - self.last_refreshed) > self.ttl

    def refresh_all_caches(self):
        if not self.broker:
            print("Broker not initialized. Please login first.")
            return
        
        if not self.cmp_manager:
            self.cmp_manager = CMPManager(csv_path="data/Name-symbol-mapping.csv", broker=self.broker, session_manager=self.session_manager, ttl=self.ttl)

        #print("🔄 Refreshing all caches...")
        self.refresh_holdings()
        self.refresh_entry_levels()
        self.refresh_gtt_cache()
        self.refresh_cmp_cache()
        self.last_refreshed = time.time()

    def refresh_holdings(self):
        self.holdings = self.broker.get_holdings()

    def refresh_entry_levels(self):
        # Assuming entry levels are broker specific
        self.entry_levels = self.broker.load_entry_levels(f"data/{self.broker.user_id}-{self.broker.broker_name}-entry-levels.csv")

    def refresh_gtt_cache(self):
        try:
            self.gtt_cache = self.broker.get_gtt_orders()
        except Exception as e:
            print(f"❌ Failed to refresh GTT cache: {e}")
            self.gtt_cache = []


    def refresh_cmp_cache(self):
            self.cmp_manager.refresh_cache(self.holdings, self.gtt_cache, self.entry_levels)

    def get_gtt_cache(self):
        if self.is_stale():
            self.refresh_all_caches()
        return self.gtt_cache

    def get_existing_gtt_symbols(self):
        if self.is_stale():
            self.refresh_all_caches()
        return {
            g.tradingsymbol.strip().upper()
            for g in self.gtt_cache
            if g.transaction_type == self.broker.TRANSACTION_TYPE_BUY
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
            logging.debug("📂 Reading GTT plan from cache: ")  
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
