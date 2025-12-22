"""
Binance Futures Adapter - Implementation for Binance USDⓈ-M Futures
"""
import logging
import time
from typing import List, Optional, Dict, Any

from binance.client import Client
from binance.exceptions import BinanceAPIException

from src.exchange_adapter import (
    ExchangeAdapter, 
    OrderResult, 
    OrderSide, 
    OrderStatus,
    Position, 
    AccountBalance, 
    MarketInfo
)

logger = logging.getLogger(__name__)


class BinanceAdapter(ExchangeAdapter):
    """
    Binance USDⓈ-M Futures adapter.
    
    Supports both mainnet and testnet:
    - Mainnet: https://fapi.binance.com
    - Testnet: https://testnet.binancefuture.com
    """
    
    TESTNET_URL = "https://testnet.binancefuture.com"
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client: Optional[Client] = None
        self._symbol_info_cache: Dict[str, MarketInfo] = {}
        
    def connect(self) -> bool:
        """Initialize Binance client."""
        try:
            self.client = Client(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet
            )
            
            # Test connection
            server_time = self.client.futures_time()
            logger.info(f"Connected to Binance {'Testnet' if self.testnet else 'Mainnet'}")
            logger.info(f"Server time: {server_time}")
            return True
            
        except BinanceAPIException as e:
            logger.error(f"Failed to connect to Binance: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to Binance: {e}")
            return False
    
    def get_account_balance(self) -> AccountBalance:
        """Get futures account balance."""
        try:
            account = self.client.futures_account()
            
            return AccountBalance(
                total_balance=float(account['totalWalletBalance']),
                available_balance=float(account['availableBalance']),
                unrealized_pnl=float(account['totalUnrealizedProfit'])
            )
        except BinanceAPIException as e:
            logger.error(f"Failed to get account balance: {e}")
            return AccountBalance(0, 0, 0)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            
            for pos in positions:
                size = float(pos['positionAmt'])
                if size != 0:
                    return Position(
                        symbol=symbol,
                        side=OrderSide.BUY if size > 0 else OrderSide.SELL,
                        size=abs(size),
                        entry_price=float(pos['entryPrice']),
                        unrealized_pnl=float(pos['unRealizedProfit']),
                        leverage=int(pos['leverage'])
                    )
            return None
            
        except BinanceAPIException as e:
            logger.error(f"Failed to get position: {e}")
            return None
    
    def get_mark_price(self, symbol: str) -> float:
        """Get mark price for a symbol."""
        try:
            ticker = self.client.futures_mark_price(symbol=symbol)
            return float(ticker['markPrice'])
        except BinanceAPIException as e:
            logger.error(f"Failed to get mark price: {e}")
            return 0.0
    
    def get_market_info(self, symbol: str) -> MarketInfo:
        """Get market info (tick size, lot size, etc.)."""
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]
            
        try:
            info = self.client.futures_exchange_info()
            
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    tick_size = 0.01
                    lot_size = 0.001
                    min_notional = 5.0
                    
                    for f in s['filters']:
                        if f['filterType'] == 'PRICE_FILTER':
                            tick_size = float(f['tickSize'])
                        elif f['filterType'] == 'LOT_SIZE':
                            lot_size = float(f['stepSize'])
                        elif f['filterType'] == 'MIN_NOTIONAL':
                            min_notional = float(f.get('notional', 5.0))
                    
                    market_info = MarketInfo(
                        symbol=symbol,
                        tick_size=tick_size,
                        lot_size=lot_size,
                        min_notional=min_notional,
                        max_leverage=int(s.get('maxLeverage', 20))
                    )
                    self._symbol_info_cache[symbol] = market_info
                    return market_info
                    
            raise ValueError(f"Symbol {symbol} not found")
            
        except BinanceAPIException as e:
            logger.error(f"Failed to get market info: {e}")
            # Return safe defaults
            return MarketInfo(symbol, 0.01, 0.001, 5.0, 20)
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        try:
            self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logger.info(f"Set leverage to {leverage}x for {symbol}")
            return True
        except BinanceAPIException as e:
            logger.error(f"Failed to set leverage: {e}")
            return False
    
    def _round_price(self, price: float, tick_size: float) -> float:
        """Round price to tick size."""
        precision = len(str(tick_size).rstrip('0').split('.')[-1])
        return round(round(price / tick_size) * tick_size, precision)
    
    def _round_quantity(self, quantity: float, lot_size: float) -> float:
        """Round quantity to lot size."""
        precision = len(str(lot_size).rstrip('0').split('.')[-1])
        return round(round(quantity / lot_size) * lot_size, precision)
    
    def place_limit_order(
        self, 
        symbol: str, 
        side: OrderSide, 
        quantity: float, 
        price: float,
        reduce_only: bool = False
    ) -> OrderResult:
        """Place a limit order."""
        try:
            market_info = self.get_market_info(symbol)
            
            # Round to proper precision
            price = self._round_price(price, market_info.tick_size)
            quantity = self._round_quantity(quantity, market_info.lot_size)
            
            response = self.client.futures_create_order(
                symbol=symbol,
                side=side.value,
                type='LIMIT',
                timeInForce='GTC',
                quantity=quantity,
                price=price,
                reduceOnly=reduce_only
            )
            
            return OrderResult(
                success=True,
                order_id=str(response['orderId']),
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                status=OrderStatus.NEW,
                raw_response=response
            )
            
        except BinanceAPIException as e:
            logger.error(f"Failed to place limit order: {e}")
            return OrderResult(success=False, error=str(e))
    
    def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reduce_only: bool = False
    ) -> OrderResult:
        """Place a market order."""
        try:
            market_info = self.get_market_info(symbol)
            quantity = self._round_quantity(quantity, market_info.lot_size)
            
            response = self.client.futures_create_order(
                symbol=symbol,
                side=side.value,
                type='MARKET',
                quantity=quantity,
                reduceOnly=reduce_only
            )
            
            return OrderResult(
                success=True,
                order_id=str(response['orderId']),
                symbol=symbol,
                side=side,
                quantity=quantity,
                status=OrderStatus.FILLED,
                raw_response=response
            )
            
        except BinanceAPIException as e:
            logger.error(f"Failed to place market order: {e}")
            return OrderResult(success=False, error=str(e))
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a specific order."""
        try:
            self.client.futures_cancel_order(
                symbol=symbol,
                orderId=int(order_id)
            )
            return True
        except BinanceAPIException as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol."""
        try:
            response = self.client.futures_cancel_all_open_orders(symbol=symbol)
            cancelled = len(response) if isinstance(response, list) else 0
            logger.info(f"Cancelled {cancelled} orders for {symbol}")
            return cancelled
        except BinanceAPIException as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return 0
    
    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all open orders for a symbol."""
        try:
            orders = self.client.futures_get_open_orders(symbol=symbol)
            return orders
        except BinanceAPIException as e:
            logger.error(f"Failed to get open orders: {e}")
            return []
    
    def bulk_place_orders(self, orders: List[Dict[str, Any]]) -> List[OrderResult]:
        """
        Place multiple orders. Binance supports batch orders up to 5 at a time.
        Orders format: [{'symbol': str, 'side': OrderSide, 'quantity': float, 'price': float}, ...]
        """
        results = []
        
        # Process in batches of 5 (Binance limit)
        for i in range(0, len(orders), 5):
            batch = orders[i:i+5]
            batch_params = []
            
            for order in batch:
                symbol = order['symbol']
                market_info = self.get_market_info(symbol)
                
                batch_params.append({
                    'symbol': symbol,
                    'side': order['side'].value if isinstance(order['side'], OrderSide) else order['side'],
                    'type': 'LIMIT',
                    'timeInForce': 'GTC',
                    'quantity': str(self._round_quantity(order['quantity'], market_info.lot_size)),
                    'price': str(self._round_price(order['price'], market_info.tick_size)),
                })
            
            try:
                response = self.client.futures_place_batch_order(batchOrders=batch_params)
                
                for r in response:
                    if 'orderId' in r:
                        results.append(OrderResult(
                            success=True,
                            order_id=str(r['orderId']),
                            symbol=r['symbol'],
                            status=OrderStatus.NEW,
                            raw_response=r
                        ))
                    else:
                        results.append(OrderResult(
                            success=False,
                            error=r.get('msg', 'Unknown error'),
                            raw_response=r
                        ))
                        
            except BinanceAPIException as e:
                logger.error(f"Batch order failed: {e}")
                # Return failure for all orders in this batch
                for _ in batch:
                    results.append(OrderResult(success=False, error=str(e)))
            
            # Small delay between batches
            if i + 5 < len(orders):
                time.sleep(0.1)
        
        return results
