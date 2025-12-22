"""
Abstract Exchange Adapter - Base class for all exchange implementations
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class OrderResult:
    """Standardized order result across exchanges"""
    success: bool
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    status: Optional[OrderStatus] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class Position:
    """Standardized position info"""
    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: int


@dataclass
class AccountBalance:
    """Standardized account balance"""
    total_balance: float
    available_balance: float
    unrealized_pnl: float


@dataclass
class MarketInfo:
    """Market metadata for a symbol"""
    symbol: str
    tick_size: float
    lot_size: float
    min_notional: float
    max_leverage: int


class ExchangeAdapter(ABC):
    """
    Abstract base class for exchange adapters.
    All exchange-specific implementations must inherit from this.
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """Initialize connection to exchange. Returns True if successful."""
        pass
    
    @abstractmethod
    def get_account_balance(self) -> AccountBalance:
        """Get account balance info."""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol. Returns None if no position."""
        pass
    
    @abstractmethod
    def get_mark_price(self, symbol: str) -> float:
        """Get current mark price for a symbol."""
        pass
    
    @abstractmethod
    def get_market_info(self, symbol: str) -> MarketInfo:
        """Get market metadata (tick size, lot size, etc.)."""
        pass
    
    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol. Returns True if successful."""
        pass
    
    @abstractmethod
    def place_limit_order(
        self, 
        symbol: str, 
        side: OrderSide, 
        quantity: float, 
        price: float,
        reduce_only: bool = False
    ) -> OrderResult:
        """Place a limit order."""
        pass
    
    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reduce_only: bool = False
    ) -> OrderResult:
        """Place a market order."""
        pass
    
    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a specific order. Returns True if successful."""
        pass
    
    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol. Returns count of cancelled orders."""
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all open orders for a symbol."""
        pass
    
    @abstractmethod
    def bulk_place_orders(self, orders: List[Dict[str, Any]]) -> List[OrderResult]:
        """Place multiple orders at once. Returns list of results."""
        pass
