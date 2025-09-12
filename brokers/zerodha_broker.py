from .base_broker import BaseBroker
from kiteconnect import KiteConnect
from core.utils import read_csv, write_csv
import os
import logging

class ZerodhaBroker(BaseBroker):
    """
    Concrete implementation for Zerodha broker.
    """

    def __init__(self, user_id, api_key, access_token):
        super().__init__(user_id)
        self.broker_name = "zerodha"
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self._trades = []
        # For compatibility with existing code that uses kite.TRANSACTION_TYPE_BUY
        self.TRANSACTION_TYPE_BUY = 'BUY'
        self.TRANSACTION_TYPE_SELL = 'SELL'
        self.GTT_TYPE_SINGLE = 'single'
        self.GTT_TYPE_OCO = 'two-leg'
        self.ORDER_TYPE_LIMIT = 'LIMIT'
        self.PRODUCT_CNC = 'CNC'


    def login(self):
        """
        Authenticate and establish a session with the broker.
        """
        # In this implementation, we assume that the access token is already available.
        # You might need to implement the full login flow to get the access token.
        logging.debug(f"Logging in to Zerodha for user {self.user_id}")
        try:
            # Get user profile to verify the connection
            profile = self.kite.profile()
            logging.debug(f"Successfully logged in as {profile['user_name']}")
        except Exception as e:
            logging.debug(f"Error logging in to Zerodha: {e}")
            raise

    def logout(self):
        """
        Log out and terminate the session.
        """
        logging.debug(f"Logging out from Zerodha for user {self.user_id}")
        try:
            # Invalidate the access token
            self.kite.invalidate_access_token()
            logging.debug("Successfully logged out from Zerodha.")
        except Exception as e:
            logging.debug(f"Error logging out from Zerodha: {e}")

    def get_holdings(self):
        """
        Retrieve the user's current holdings.
        """
        logging.debug("Getting holdings from Zerodha")
        try:
            #logging.debug(f"Holding : {self.kite.holdings()}")
            return self.kite.holdings()
        except Exception as e:
            logging.debug(f"Error getting holdings from Zerodha: {e}")
            return []

    def get_gtt_orders(self):
        """
        Retrieve the user's Good Till Triggered (GTT) orders.
        """
        logging.debug("Getting GTT orders from Zerodha")
        try:
            #logging.debug(f"Z return GTT Orders: {self.kite.get_gtts()}")
            return self.kite.get_gtts()
        except Exception as e:
            logging.debug(f"Error getting GTT orders from Zerodha: {e}")
            return []

    def get_trades(self):
        """
        Retrieve the user's trades from the trade book.
        """
        file_path = f"data/{self.user_id}_trade_book.csv"
        logging.debug(f"Getting trades from {file_path} for Zerodha")
        if os.path.exists(file_path):
            self._trades = read_csv(file_path)
        logging.debug(f"Trades: {self._trades}")
        return self._trades

    def trades(self):
        """
        Retrieve the user's trades from the broker's API.
        """
        logging.debug("Getting trades from Zerodha API")
        try:
            return self.kite.trades()
        except Exception as e:
            logging.debug(f"Error getting trades from Zerodha API: {e}")
            return []

    def place_order(self, order_details):
        """
        Place an order with the broker.
        """
        logging.debug(f"Placing order in Zerodha: {order_details}")
        try:
            return self.kite.place_order(
                variety=order_details['variety'],
                exchange=order_details['exchange'],
                tradingsymbol=order_details['tradingsymbol'],
                transaction_type=order_details['transaction_type'],
                quantity=order_details['quantity'],
                product=order_details['product'],
                order_type=order_details['order_type'],
                price=order_details.get('price'),
                trigger_price=order_details.get('trigger_price')
            )
        except Exception as e:
            logging.debug(f"Error placing order in Zerodha: {e}")
            raise

    def place_gtt(self, **kwargs):
        """
        Place a GTT order.
        """
        #logging.debug(f"Placing GTT in Zerodha: {kwargs}")
        try:
            return self.kite.place_gtt(**kwargs)
        except Exception as e:
            logging.debug(f"Error placing GTT in Zerodha: {e}")
            raise

    def modify_gtt(self, gtt_order):
        """
        Modify an existing GTT order.
        """
        logging.debug(f"Modifying GTT in Zerodha: {gtt_order}")
        try:
            return self.kite.modify_gtt(
                trigger_id=gtt_order['trigger_id'],
                tradingsymbol=gtt_order['tradingsymbol'],
                exchange=gtt_order['exchange'],
                trigger_values=gtt_order['trigger_values'],
                last_price=gtt_order['last_price'],
                orders=gtt_order['orders']
            )
        except Exception as e:
            logging.debug(f"Error modifying GTT in Zerodha: {e}")
            raise

    def cancel_gtt(self, order_id):
        """
        Cancel a GTT order.
        """
        logging.debug(f"Cancelling GTT in Zerodha: {order_id}")
        try:
            return self.kite.delete_gtt(trigger_id=order_id)
        except Exception as e:
            logging.debug(f"Error cancelling GTT in Zerodha: {e}")
            raise

    def load_entry_levels(self, file_path):
        """
        Load entry levels from a broker-specific file.
        """
        logging.debug(f"Loading entry levels from {file_path} for Zerodha")
        if os.path.exists(file_path):
            return read_csv(file_path)
        return []

    def update_roi_master(self, data):
        """
        Update the ROI master file for the broker.
        """
        file_path = f"data/{self.user_id}_roi_master.csv"
        logging.debug(f"Updating ROI master file for Zerodha: {file_path}")
        write_csv(file_path, data)


    def update_trade_book(self, data):
        """
        Update the trade book master file for the broker.
        """
        file_path = f"data/{self.user_id}_trade_book.csv"
        logging.debug(f"Updating trade book for Zerodha: {file_path}")
        write_csv(file_path, data)