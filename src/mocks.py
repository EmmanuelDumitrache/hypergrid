class MockExchange:
    def __init__(self):
        self.orders = []
        
    def cancel_all_orders(self):
        print("MOCK: Cancelled all orders")
        self.orders = []
        
    def market_close(self, coin):
        print(f"MOCK: Market closed {coin}")
        
    def update_leverage(self, leverage, coin, is_cross):
        print(f"MOCK: Updated leverage for {coin} to {leverage}x (Cross: {is_cross})")

    def bulk_orders(self, orders):
        print(f"MOCK: Placed {len(orders)} orders")
        self.orders.extend(orders)
        return {"status": "ok", "statuses": ["filled"] * len(orders)}

class MockInfo:
    def user_state(self, address):
        return {
            'marginSummary': {
                'accountValue': '500.0',
                'totalMarginUsed': '100.0'
            },
            'openOrders': [],
            'assetPositions': [
                {'position': {'coin': 'SOL', 'szi': '10.0'}}
            ]
        }
    
    def all_mids(self):
        return {'SOL': '135.50'}

    def meta_and_asset_ctxs(self):
        # Mock universe and ctx for SOL
        meta = {'universe': [{'name': 'BTC'}, {'name': 'SOL'}]}
        # asset_ctxs corresponding to universe
        # Let's say SOL has high finding
        btc_ctx = {'funding': '0.00001'}
        sol_ctx = {'funding': '0.00002'} # Normal
        return meta, [btc_ctx, sol_ctx]
