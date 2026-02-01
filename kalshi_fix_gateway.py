# Will need to covert to use quickfix

import asyncio
import logging
from aiopyfix import FIXClient, FIXMessage, ConnectionState
from aiopyfix import MessageDirection

class KalshiFIXGateway:
    def __init__(self, host, port, sender_comp_id, target_comp_id, fix_version, heartbeat_interval, loop=None):
        self.host = host
        self.port = port
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.fix_version = fix_version
        self.heartbeat_interval = heartbeat_interval
        self.loop = loop or asyncio.get_event_loop()
        self.client = FIXClient(fix_version, 
                                host=self.host, 
                                port=self.port,
                                sender_comp_id=self.sender_comp_id,
                                target_comp_id=self.target_comp_id)
        
        self.session = None
        
        #Heartbeating
        self.heartbeat_task = None
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(level=logging.INFO,
                             format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                             datefmt='%m/%d/%Y %H:%M:%S',
                             filename='kalshi_gateway_app.log',
                             filemode='a')

    async def connect(self):
        """
        Starts session handshake and wait for FIX Logon.
        """
        self.logger.info("Starting FIX client...")
        self.client.addConnectionStateListener(self.on_connect, ConnectionState.CONNECTED)
        self.client.addConnectionStateListener(self.on_disconnect, ConnectionState.DISCONNECTED)
        
        # Initiate TCP connection and FIX log on
        await self.client.start(self.host, self.port, loop=self.loop)
        
    async def on_connect(self, session):
        """
        Called when TCP and FIX connection completes
        """
        pass

    async def on_disconnect(self):
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
