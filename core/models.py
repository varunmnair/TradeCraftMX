
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Holding:
    tradingsymbol: str
    exchange: str
    instrument_token: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    close_price: float
    product: str

@dataclass
class GTTOrder:
    id: int
    created_at: str
    instrument_token: str
    tradingsymbol: str
    exchange: str
    trigger_values: List[float]
    quantity: int
    transaction_type: str
    price: float
    status: str
    type: str
