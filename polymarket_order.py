# Will need to covert to use quickfix

import asyncio
import logging
from aiopyfix import FIXClient, FIXMessage, ConnectionState
from aiopyfix import MessageDirection

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

FIX_VERSION  = "aiopyfix.FIXT11"  # Transport/session version = FIXT.1.1
SENDER_COMP  = "SENDER"          # Replace with your assigned SenderCompID
TARGET_COMP  = "TARGET"          # Replace with your TARGET CompID (exchange)
HOST         = "fix.polymarket.com"  # Replace with Polymarket FIX host
PORT         = 9876                 # Replace with real FIX port

LOGON_HEARTBEAT_INTERVAL = 30  # Heartbeat interval in seconds

class PolymarketFIXGateway:
    def __init__(self, host, port, sender_comp_id, target_comp_id, fix_version, heartbeat_interval, loop = None):
        self.host = host
        self.port = port
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.fix_version = fix_version
        self.heartbeat_interval = heartbeat_interval
        self.loop = loop or asyncio.get_event_loop()
        self.client = FIXClient(self.fix_version,
                                sender_comp_id=self.sender_comp_id,
                                target_comp_id=self.target_comp_id,
                                host=self.host,
                                port=self.port)
        self.session = None
        
        # Heartbeating
        self._heartbeat_task = None
        
        self.logger = logging.getLogger("PolymarketFIXGateway")
        self.logger.setLevel(level=logging.INFO,
                             format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                             datefmt='%m/%d/%Y %H:%M:%S',
                             filename='app.log',
                             filemode='a')

    async def connect(self):
        """
        Starts session handshake and wait for FIX Logon.
        """
        self.logger.info("Starting FIX client...")
        self.client.addConnectionStateListener(self.on_connect, ConnectionState.CONNECTED)
        self.client.addConnectionStateListener(self.on_disconnect, ConnectionState.DISCONNECTED)
        
        # Initiates TCP connection and FIX Logon
        await self.client.start(self.host, self.port, loop=self.loop)
        
    async def on_connect(self, session):
        """
        Called when TCP + FIX handshake completes.
        """
        self.logger.info("Connected to FIX server!")
        self.session = session

        # Register inbound handler for Execution Reports (35=8)
        session.addMessageHandler(self.on_execution_report, MessageDirection.INBOUND, session.protocol.msgtype.EXECUTIONREPORT)

        # After logon, start heartbeats
        self._heartbeat_task = asyncio.create_task(self._send_heartbeat())

    async def on_disconnect(self):
        """
        Called when disconnected from FIX server.
        """
        self.logger.warning("Disconnected from FIX server")
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            
    async def _send_heartbeat(self):
        """
        Sends a heartbeat every self.heartbeat_interval seconds to keep connection alive.
        """
        while True:
            try:
                heartbeat_msg = FIXMessage(self.session.codec.protocol.msgtype.HEARTBEAT)
                await self.session.sendMsg(self.session.codec.pack(heartbeat_msg, self.session))
                self.logger.debug("Sent Heartbeat")
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error sending heartbeat: {e}")
                break

    async def send_order(self, order: FIXMessage):
        await self.session.sendMsg(self.session.codec.pack(order, self.session))

    async def on_message(self, msg: FIXMessage):
        self.logger.info(f"Received message: {msg}")

if __name__ == "__main__":
    polymarket_fix_gateway = PolymarketFIXGateway()