from abc import ABC, abstractmethod

class BaseBroker(ABC):
    """
    Abstract base class for all broker implementations.
    """

    def __init__(self, user_id):
        self.user_id = user_id

    @abstractmethod
    def login(self):
        """
        Authenticate and establish a session with the broker.
        """
        pass

    @abstractmethod
    def logout(self):
        """
        Log out and terminate the session.
        """
        pass

    @abstractmethod
    def get_holdings(self):
        """
        Retrieve the user's current holdings.
        """
        pass

    @abstractmethod
    def get_gtt_orders(self):
        """
        Retrieve the user's Good Till Triggered (GTT) orders.
        """
        pass

    @abstractmethod
    def get_trades(self):
        """
        Retrieve the user's trades.
        """
        pass

    @abstractmethod
    def place_order(self, order_details):
        """
        Place an order with the broker.
        """
        pass

    @abstractmethod
    def modify_gtt(self, gtt_order):
        """
        Modify an existing GTT order.
        """
        pass

    @abstractmethod
    def cancel_gtt(self, order_id):
        """
        Cancel a GTT order.
        """
        pass

    @abstractmethod
    def load_entry_levels(self, file_path):
        """
        Load entry levels from a broker-specific file.
        """
        pass

    @abstractmethod
    def update_roi_master(self, data):
        """
        Update the ROI master file for the broker.
        """
        pass

    @abstractmethod
    def update_trade_book(self, data):
        """
        Update the trade book master file for the broker.
        """
        pass

    @abstractmethod
    def download_historical_trades(self, start_date, end_date):
        """
        Download historical trades from the broker.
        """
        pass


