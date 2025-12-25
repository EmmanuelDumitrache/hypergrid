import logging
import time
import asyncio
import threading
from binance import AsyncClient, BinanceSocketManager

class WebSocketManager:
    """
    Manages WebSocket connections using AsyncClient and BinanceSocketManager 
    in a dedicated thread to avoid event loop conflicts.
    """
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.symbol = None
        self.price_callback = None
        self.user_callback = None
        
        self.loop = None
        self.thread = None
        self.running = False
        self.client = None
        self.bm = None

    def start(self, symbol, price_callback, user_callback):
        """Start the WebSocket manager in a separate thread."""
        self.symbol = symbol
        self.price_callback = price_callback
        self.user_callback = user_callback
        self.running = True
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the loop and thread."""
        self.running = False
        if self.loop:
            # This is a bit rough, but effective for stopping the async loop from outside
            asyncio.run_coroutine_threadsafe(self._stop_client(), self.loop)
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        
        logging.info("🔌 WebSockets stopped.")

    def _run_loop(self):
        """Entry point for the dedicated thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _stop_client(self):
        if self.client:
            await self.client.close_connection()

    async def _main(self):
        """Main async task."""
        logging.info("🔌 Connecting to Binance WebSockets (Async)...")
        self.client = await AsyncClient.create(self.api_key, self.api_secret, testnet=self.testnet)
        self.bm = BinanceSocketManager(self.client)
        
        # Create tasks for streams
        tasks = []
        
        # 1. Price Stream
        formatted_symbol = self.symbol.lower()
        # Note: Futures stream names are slightly different. 
        # For coin-m uses symbol_ticker, for usdt-m uses symbol_ticker as well.
        ts = self.bm.symbol_ticker_socket(self.symbol)
        tasks.append(asyncio.create_task(self._monitor_stream(ts, 'PRICE')))
        logging.info(f"   └─ Subscribed to price updates for {self.symbol}")

        # 2. User Stream
        # For futures, we need to generate listen key first? 
        # BinanceSocketManager handles this logic internally usually?
        # Let's use futures_user_socket logic.
        # But wait, python-binance `futures_user_socket` might require manual listen key management in older versions.
        # The latest version manages it. 
        # IMPORTANT: Testnet User Streams are notoriously unstable.
        
        # We will try standard user socket
        us = self.bm.futures_user_socket()
        tasks.append(asyncio.create_task(self._monitor_stream(us, 'USER')))
        logging.info("   └─ Subscribed to user data updates")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"WebSocket Error: {e}")
        finally:
            await self.client.close_connection()

    async def _monitor_stream(self, stream, stream_type):
        """Generic stream monitor."""
        async with stream as tscm:
            while self.running:
                try:
                    res = await tscm.recv()
                    if res:
                        if stream_type == 'PRICE':
                            self._handle_price_msg(res)
                        elif stream_type == 'USER':
                            self._handle_user_msg(res)
                except Exception as e:
                    if self.running:
                         logging.error(f"Stream error ({stream_type}): {e}")
                         # Simple retry delay
                         await asyncio.sleep(5)
                
    def _handle_price_msg(self, msg):
        # msg format: {'e': '24hrTicker', 'c': '844.00', ...}
        # Or sometimes just dict.
        try:
            if 'c' in msg:
                price = float(msg['c'])
                if self.price_callback:
                    self.price_callback(price)
        except:
            pass

    def _handle_user_msg(self, msg):
        try:
            event_type = msg.get('e')
            if event_type == 'ORDER_TRADE_UPDATE':
                order_data = msg.get('o')
                if self.user_callback:
                    self.user_callback('ORDER', order_data)
        except:
            pass
