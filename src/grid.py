import logging
import numpy as np

logger = logging.getLogger(__name__)

class GridManager:
    def __init__(self, config, exchange):
        self.config = config
        self.exchange = exchange
        self.num_grids = config['grid']['grids']
        self.spacing = config['grid']['spacing_pct']
        self.leverage = config['grid']['leverage']
        self.active_orders = []

    def calculate_levels(self, current_price):
        """
        Calculate grid levels around current price.
        25 grids total. 
        If neutral: 12 buys below, 12 sells above? Or 25 buys if aiming to long?
        Spec: "Pair: SOL/USD perpetuals ... 25 grids ... around current price"
        Usually implies Neutral Grid.
        """
        # Half grids on each side
        half_grids = self.num_grids // 2
        
        buy_levels = []
        sell_levels = []
        
        # Calculate levels relative to current price
        # Buy levels: Price * (1 - spacing * i)
        for i in range(1, half_grids + 1):
            price = current_price * (1 - (self.spacing * i))
            buy_levels.append(price)
            
        # Sell levels: Price * (1 + spacing * i)
        for i in range(1, half_grids + 1):
            price = current_price * (1 + (self.spacing * i))
            sell_levels.append(price)
            
        return sorted(buy_levels), sorted(sell_levels)

    def place_initial_orders(self, current_price):
        """
        Place initial batch of orders.
        """
        buy_levels, sell_levels = self.calculate_levels(current_price)
        
        orders = []
        
        # Calculate size per grid
        # Capital * Leverage / Num Grids?
        # User config: Capital $500, Leverage 1.5x. Total power $750.
        # Per grid: $750 / 25 = $30. 
        # But wait, 30% cash reserve required!
        # Max deployed = 70% of Capital.
        # Deployed Capital = $500 * 0.7 = $350.
        # Total Position Value allowed = $350 * 1.5 (Lev) = $525? 
        # Or is 30% reserve on the raw capital? usually reserve is on equity.
        # Start Capital: $500. Reserve $150. Trade with $350.
        # Leverage 1.5x on $350 ?? Or 1.5x on the whole account but only use 70% margin?
        # "1.5x ISOLATED margin ONLY".
        # Let's interpret: Total Max Position Value should not exceed ($500 * 0.70) * Levr? 
        # Or ($500 * 1.5) * 0.70?
        # Simpler: Allocation per grid.
        # Total usable balance = Capital * 0.7.
        # Size per grid (USD) = (Total Usable * Leverage) / Grids ??
        # Let's be safe: (Capital * 0.7 * Leverage) / grids.
        # (500 * 0.7 * 1.5) / 25 = 525 / 25 = $21 USD size per order.
        
        capital = self.config['grid']['capital']
        reserve_ratio = 1.0 - 0.7 # 30% reserve means 70% deployed
        deployed_capital = capital * 0.7
        total_size_usd = deployed_capital * self.leverage
        size_per_grid_usd = total_size_usd / self.num_grids
        
        logger.info(f"Initializing Grid. Price: {current_price}. Size per grid: ${size_per_grid_usd:.2f}")

        # Place Buys
        for price in buy_levels:
            sz_coin = size_per_grid_usd / price
            # Round logic for Hyperliquid (api usually handles or need util)
            # We'll use formatting .4f for now
            order = {
                'coin': self.config['grid']['pair'],
                'is_buy': True,
                'sz': float(f"{sz_coin:.4f}"),
                'limit_px': float(f"{price:.4f}"),
                'order_type': {'limit': {'tif': 'Gtc'}},
                'reduce_only': False
            }
            orders.append(order)
            
        # Place Sells
        for price in sell_levels:
            sz_coin = size_per_grid_usd / price
            order = {
                'coin': self.config['grid']['pair'],
                'is_buy': False,
                'sz': float(f"{sz_coin:.4f}"),
                'limit_px': float(f"{price:.4f}"),
                'order_type': {'limit': {'tif': 'Gtc'}},
                'reduce_only': False
            }
            orders.append(order)
            
        logger.info(f"Generated {len(orders)} initial orders.")
        
        # Execute Batch
        # self.exchange.bulk_orders(orders) -> Not standard SDK?
        # SDK usually has `exchange.order` or `exchange.bulk_orders`.
        # We will assume `order` loop for MVP or look for bulk if known.
        # Hyperliquid SDK usually supports checking batching.
        
        return orders

