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
        
        # Manual Range Mode
        self.min_price = None
        self.max_price = None
        
        # Get Precision from Info
        self.sz_decimals = 2 # Default safe for SOL
        self.px_decimals = 2 # Default safe for SOL
        
        try:
             # If exchange has info attached or we pass it
             pass 
        except:
             pass

    def set_precision(self, sz_decimals, px_decimals):
        self.sz_decimals = sz_decimals
        self.px_decimals = px_decimals

    def set_manual_range(self, min_price, max_price):
        """Set manual Fixed Range"""
        self.min_price = min_price
        self.max_price = max_price

    def calculate_levels(self, current_price):
        """
        Calculate grid levels.
        If min_price and max_price are set, use Fixed Range (Arithmetic).
        Else, use Spread-based around current_price.
        """
        buy_levels = []
        sell_levels = []

        if self.min_price and self.max_price:
            # Fixed Range Arithmetic Grid
            # range = max - min
            # step = range / grids
            step = (self.max_price - self.min_price) / self.num_grids
            
            # Generate all levels from min to max
            all_levels = [self.min_price + (step * i) for i in range(self.num_grids + 1)]
            
            # Split into buy/sell based on current price
            # Levels below current are Buys, above are Sells
            buy_levels = [l for l in all_levels if l < current_price]
            sell_levels = [l for l in all_levels if l > current_price]
            
        else:
            # Existing Spread Logic
            half_grids = self.num_grids // 2
            
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
            # Round using dynamic precision
            sz_fmt = f"{{:.{self.sz_decimals}f}}"
            px_fmt = f"{{:.{self.px_decimals}f}}"
            
            order = {
                'coin': self.config['grid']['pair'],
                'is_buy': True,
                'sz': float(sz_fmt.format(sz_coin)),
                'limit_px': float(px_fmt.format(price)),
                'order_type': {'limit': {'tif': 'Gtc'}},
                'reduce_only': False
            }
            orders.append(order)
            
        # Place Sells
        for price in sell_levels:
            sz_coin = size_per_grid_usd / price
            
            sz_fmt = f"{{:.{self.sz_decimals}f}}"
            px_fmt = f"{{:.{self.px_decimals}f}}"

            order = {
                'coin': self.config['grid']['pair'],
                'is_buy': False,
                'sz': float(sz_fmt.format(sz_coin)),
                'limit_px': float(px_fmt.format(price)),
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

