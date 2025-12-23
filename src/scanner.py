import logging
import time

class MarketScanner:
    def __init__(self, exchange_adapter, whitelist, check_interval_minutes=240):
        self.exchange = exchange_adapter
        self.whitelist = whitelist
        self.check_interval = check_interval_minutes * 60
        self.last_check = 0
        self.best_pair = None

    def find_best_pair(self):
        """Scan whitelist for best volatility/volume opportunities."""
        now = time.time()
        if now - self.last_check < self.check_interval:
            return None

        self.last_check = now
        logging.info("🔎 Scanning market for best pair...")
        
        scores = []
        
        for symbol in self.whitelist:
            try:
                # Use the underlying client to get 24hr ticker
                ticker = self.exchange.client.get_ticker(symbol=symbol)
                
                # Extract metrics
                volatility_pct = float(ticker['priceChangePercent']) # This is simple 24h change, adequate proxy for trendiness/vol
                volume_usdt = float(ticker['quoteVolume'])
                
                # simple score: absolute volatility * log(volume) or just raw volume weight
                # We want: Moving sideways but with high variance. 
                # Actually, 24h change isn't volatility. True volatility needs candles.
                # But for a simple scanner, High Vol + High Volume is "Action".
                
                score = abs(volatility_pct) * (volume_usdt / 1_000_000)
                scores.append((symbol, score, volatility_pct, volume_usdt))
                
            except Exception as e:
                logging.warning(f"Failed to scan {symbol}: {e}")
                
        if not scores:
            return None
            
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        top_pick = scores[0]
        logging.info(f"🏆 Scanner Result: Best Pair is {top_pick[0]} (Score: {top_pick[1]:.1f})")
        
        self.best_pair = top_pick[0]
        return self.best_pair
