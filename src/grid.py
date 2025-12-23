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
        self.tick_size = 0.001  # Default for SOL/USD
        
        try:
             # If exchange has info attached or we pass it
             pass 
        except:
             pass
             
        # Initialize Valid Grid Size
        self.size_per_grid_usd = self._calculate_grid_size()

    def _calculate_grid_size(self):
        """Calculate grid size with minimum order enforcement"""
        capital = self.config['grid']['capital']
        deployed_capital = capital * 0.7 # 70% deployed, 30% reserve
        total_size_usd = deployed_capital * self.leverage
        size_per_grid_usd = total_size_usd / self.num_grids
        
        # Min Order Size Check (Hyperliquid usually requires ~$10-12 USD)
        min_order_size = 12.0
        if size_per_grid_usd < min_order_size:
            logger.warning(f"Calculated grid size ${size_per_grid_usd:.2f} is below minimum ${min_order_size}!")
            logger.warning(f"Enforcing minimum size ${min_order_size}. CAUTION: This may increase total position size.")
            size_per_grid_usd = min_order_size
            
        return size_per_grid_usd

    def round_to_tick(self, price):
        """Round price to nearest tick size"""
        return round(price / self.tick_size) * self.tick_size

    def set_precision(self, sz_decimals, px_decimals, tick_size=None):
        self.sz_decimals = sz_decimals
        self.px_decimals = px_decimals
        if tick_size:
            self.tick_size = tick_size
            logger.info(f"GridManager precision updated: Size {sz_decimals}, Price {px_decimals}, Tick {tick_size}")


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
            
            
        # Round all levels to tick size
        buy_levels = [self.round_to_tick(p) for p in buy_levels]
        sell_levels = [self.round_to_tick(p) for p in sell_levels]
        
        return sorted(buy_levels), sorted(sell_levels)

    def calculate_volatility_range(self, current_price, high_24h, low_24h):
        """
        Calculate and set range based on 24h volatility.
        Logic: Range = min(Volatility * 2, 10%)
        """
        if current_price <= 0:
            return
            
        vol_24h = (high_24h - low_24h) / current_price if current_price > 0 else 0.03
        
        # Safe default if vol is zero or crazy
        if vol_24h <= 0: vol_24h = 0.01
        
        # Conservative: 2x daily volatility
        range_pct = min(vol_24h * 2, 0.10)  # Max 10% range
        if range_pct < 0.02: range_pct = 0.02 # Min 2% range
        
        self.min_price = self.round_to_tick(current_price * (1 - range_pct))
        self.max_price = self.round_to_tick(current_price * (1 + range_pct))
        
        logger.info(f"AUTO-RANGE Recalculated: ${self.min_price:.3f} - ${self.max_price:.3f} (Vol: {vol_24h*100:.1f}%)")

    def place_initial_orders(self, current_price):
        """
        Place initial batch of orders.
        """
        buy_levels, sell_levels = self.calculate_levels(current_price)
        
        orders = []
        
        # Use pre-calculated enforced size
        size_per_grid_usd = self.size_per_grid_usd
        
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

    def get_counter_order(self, filled_order):
        """
        Generate a counter-order (flip) for a filled order.
        """
        fill_price = filled_order['price']
        is_buy_fill = filled_order['side'] == 'BUY'
        
        # Determine Counter Side
        is_counter_buy = not is_buy_fill
        
        # Calculate Counter Price
        if is_buy_fill:
             # Filled Buy -> Place Sell higher
             new_price = fill_price * (1 + self.spacing)
        else:
             # Filled Sell -> Place Buy lower
             new_price = fill_price * (1 - self.spacing)
             
        new_price = self.round_to_tick(new_price)
        
        # Calculate Size
        # If we stored size_per_grid_usd, use it. Else roughly infer from fill?
        # Better to recalculate from capital to keep alignment, or use the filled size if we want to be "neutral" (not really neutral but simple).
        # Let's try to use stored size if available, else derive.
        size_usd = getattr(self, 'size_per_grid_usd', 20.0) # Default fallback
        new_sz_coin = size_usd / new_price
        
        sz_fmt = f"{{:.{self.sz_decimals}f}}"
        px_fmt = f"{{:.{self.px_decimals}f}}"
        
        counter_order = {
            'coin': self.config['grid']['pair'],
            'is_buy': is_counter_buy,
            'sz': float(sz_fmt.format(new_sz_coin)),
            'limit_px': float(px_fmt.format(new_price)),
            'order_type': {'limit': {'tif': 'Gtc'}},
            'reduce_only': False
        }
        
        logger.info(f"Generated Counter-Order: {'BUY' if is_counter_buy else 'SELL'} {counter_order['sz']} @ ${counter_order['limit_px']} (Flip from ${fill_price})")
        return counter_order

