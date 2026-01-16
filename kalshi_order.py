# Will need to covert to use quickfix

import asyncio
import logging
from aiopyfix import FIXClient, FIXMessage, ConnectionState
from aiopyfix import MessageDirection

class KalshiFIXGateway:
    def __init__(self, host, port):
        self.client = FIXClient(host, port)
        self.logger = logging.getLogger(__name__)

    async def connect(self):
        await self.client.connect()

    async def disconnect(self):
        await self.client.disconnect()

    async def send_order(self, order):
        msg = FIXMessage()
        msg.set_field(35, "D")  # Message type: New Order - Single
        msg.set_field(55, order.symbol)
        msg.set_field(54, order.side)
        msg.set_field(38, order.quantity)
        msg.set_field(44, order.price)
        await self.client.send(msg)

    async def on_message(self, msg):
        self.logger.info(f"Received FIX message: {msg}")
