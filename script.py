import os
import time
import json
import logging
import sys
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError, BadFunctionCallOutput

# --- Configuration Setup ---
# Configure logging to provide detailed output.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    stream=sys.stdout
)

# Load environment variables from a .env file for security and flexibility.
load_dotenv()

# --- Constants and Mock Data ---
# In a real-world scenario, these ABIs would be loaded from JSON files.
# This mock ABI represents a simplified cross-chain bridge contract.
BRIDGE_CONTRACT_ABI = json.loads('''
[
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": true, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": false, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"},
            {"indexed": false, "internalType": "uint256", "name": "nonce", "type": "uint256"}
        ],
        "name": "TokensLocked",
        "type": "event"
    },
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": true, "internalType": "uint256", "name": "nonce", "type": "uint256"}
        ],
        "name": "TokensReleased",
        "type": "event"
    }
]
''')

# Default poll interval in seconds if not specified in the environment.
DEFAULT_POLL_INTERVAL = 15.0

class ConfigManager:
    """Manages retrieval of configuration from environment variables."""

    @staticmethod
    def get_rpc_url(chain_name: str) -> str:
        """
        Fetches the RPC URL for a given chain from environment variables.

        Args:
            chain_name (str): The name of the chain (e.g., 'SOURCE_CHAIN').

        Returns:
            str: The RPC URL.

        Raises:
            ValueError: If the corresponding environment variable is not set.
        """
        var_name = f"{chain_name.upper()}_RPC_URL"
        rpc_url = os.getenv(var_name)
        if not rpc_url:
            raise ValueError(f"Environment variable {var_name} is not set.")
        return rpc_url

    @staticmethod
    def get_contract_address(chain_name: str) -> str:
        """
        Fetches the bridge contract address for a given chain.

        Args:
            chain_name (str): The name of the chain (e.g., 'SOURCE_CHAIN').

        Returns:
            str: The checksummed contract address.

        Raises:
            ValueError: If the corresponding environment variable is not set.
        """
        var_name = f"{chain_name.upper()}_BRIDGE_CONTRACT_ADDRESS"
        address = os.getenv(var_name)
        if not address:
            raise ValueError(f"Environment variable {var_name} is not set.")
        return Web3.to_checksum_address(address)

    @staticmethod
    def get_relayer_api_endpoint() -> str:
        """
        Fetches the endpoint for the mock relayer service.

        Returns:
            str: The API endpoint URL.

        Raises:
            ValueError: If the RELAYER_API_ENDPOINT variable is not set.
        """
        endpoint = os.getenv("RELAYER_API_ENDPOINT")
        if not endpoint:
            raise ValueError("Environment variable RELAYER_API_ENDPOINT is not set.")
        return endpoint

    @staticmethod
    def get_poll_interval() -> float:
        """Fetches the event polling interval from the environment."""
        interval = os.getenv("POLL_INTERVAL")
        try:
            return float(interval) if interval else DEFAULT_POLL_INTERVAL
        except ValueError:
            logging.warning(f"Invalid POLL_INTERVAL value '{interval}'. Using default {DEFAULT_POLL_INTERVAL}s.")
            return DEFAULT_POLL_INTERVAL


class BlockchainConnector:
    """
    Handles connection to a single blockchain node via Web3.py.
    Encapsulates connection logic, retries, and contract instantiation.
    """

    def __init__(self, chain_name: str, rpc_url: str):
        """
        Initializes the connector for a specific chain.

        Args:
            chain_name (str): A descriptive name for the chain (e.g., 'Ethereum_Sepolia').
            rpc_url (str): The HTTP RPC endpoint for the blockchain node.
        """
        self.chain_name = chain_name
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def connect(self, max_retries: int = 3, delay: int = 5) -> bool:
        """
        Establishes and verifies the connection to the blockchain node.

        Args:
            max_retries (int): Maximum number of connection attempts.
            delay (int): Delay in seconds between retries.

        Returns:
            bool: True if connection is successful, False otherwise.
        """
        for attempt in range(max_retries):
            try:
                self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if self.web3.is_connected():
                    chain_id = self.web3.eth.chain_id
                    self.logger.info(f"Successfully connected to {self.chain_name} (Chain ID: {chain_id}).")
                    return True
                else:
                    raise ConnectionError("web3.is_connected() returned False.")
            except Exception as e:
                self.logger.error(
                    f"Connection attempt {attempt + 1}/{max_retries} to {self.chain_name} failed: {e}"
                )
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
        self.logger.critical(f"Could not connect to {self.chain_name} after {max_retries} attempts.")
        return False

    def get_contract(self, address: str, abi: Dict[str, Any]) -> Optional[Contract]:
        """
        Creates a Web3.py Contract instance.

        Args:
            address (str): The contract address.
            abi (Dict[str, Any]): The contract's ABI.

        Returns:
            Optional[Contract]: A contract instance if connected, otherwise None.
        """
        if not self.web3 or not self.web3.is_connected():
            self.logger.error(f"Cannot get contract. Not connected to {self.chain_name}.")
            return None
        try:
            return self.web3.eth.contract(address=address, abi=abi)
        except Exception as e:
            self.logger.error(f"Failed to instantiate contract at {address} on {self.chain_name}: {e}")
            return None

    def get_latest_block_number(self) -> Optional[int]:
        """Fetches the latest block number from the connected node."""
        if self.web3 and self.web3.is_connected():
            return self.web3.eth.block_number
        self.logger.warning(f"Cannot get latest block number. Not connected to {self.chain_name}.")
        return None


class EventProcessor:
    """
    Processes blockchain events and triggers corresponding actions,
    such as notifying a relayer service.
    """

    def __init__(self, relayer_api_endpoint: str):
        """
        Initializes the processor.

        Args:
            relayer_api_endpoint (str): The URL of the relayer service to notify.
        """
        self.relayer_api_endpoint = relayer_api_endpoint
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.logger = logging.getLogger(self.__class__.__name__)

    def process_and_notify(self, event: Dict[str, Any], source_chain_name: str):
        """
        Processes a raw event, formats a payload, and notifies the relayer.

        Args:
            event (Dict[str, Any]): The event data from web3.py.
            source_chain_name (str): The name of the chain where the event originated.
        """
        self.logger.info(f"Processing event '{event['event']}' from transaction {event['transactionHash'].hex()}")

        # In a real system, you would perform more complex validation and formatting.
        payload = {
            "eventName": event['event'],
            "sourceChain": source_chain_name,
            "transactionHash": event['transactionHash'].hex(),
            "blockNumber": event['blockNumber'],
            "eventData": {
                # Convert bytes and other web3 types to JSON-serializable formats.
                key: str(value) if isinstance(value, bytes) else value
                for key, value in event['args'].items()
            }
        }

        self.logger.debug(f"Formatted payload: {json.dumps(payload, indent=2)}")
        self._notify_relayer(payload)

    def _notify_relayer(self, payload: Dict[str, Any]):
        """
        Sends the processed event data to the relayer service via an HTTP POST request.
        This is a simulation; in a real bridge, this would trigger the destination chain transaction.

        Args:
            payload (Dict[str, Any]): The JSON payload to send.
        """
        try:
            response = self.session.post(self.relayer_api_endpoint, json=payload, timeout=10)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

            self.logger.info(
                f"Successfully notified relayer. Status: {response.status_code}, Response: {response.json()}"
            )
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to notify relayer service at {self.relayer_api_endpoint}: {e}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during relayer notification: {e}")


class CrossChainEventListener:
    """
    The main orchestrator for the event listener service.
    It sets up connections, creates event filters, and runs the main listening loop.
    """

    def __init__(self):
        """Initializes all components required for the listener."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing ONE2U Cross-Chain Event Listener...")

        try:
            # 1. Load Configuration
            self.config = ConfigManager()
            self.poll_interval = self.config.get_poll_interval()

            # 2. Setup Blockchain Connections
            source_rpc = self.config.get_rpc_url('SOURCE_CHAIN')
            self.source_connector = BlockchainConnector('SOURCE_CHAIN', source_rpc)

            # 3. Setup Event Processor
            relayer_api = self.config.get_relayer_api_endpoint()
            self.event_processor = EventProcessor(relayer_api)

        except ValueError as e:
            self.logger.critical(f"Configuration error: {e}. Shutting down.")
            sys.exit(1)

        self.source_contract: Optional[Contract] = None
        self.is_running = True

    def _setup(self) -> bool:
        """Establishes connections and prepares contracts and filters."""
        # Connect to the source chain
        if not self.source_connector.connect():
            return False

        # Instantiate the source contract
        source_address = self.config.get_contract_address('SOURCE_CHAIN')
        self.source_contract = self.source_connector.get_contract(source_address, BRIDGE_CONTRACT_ABI)
        if not self.source_contract:
            return False

        self.logger.info("Setup complete. Ready to start listening for events.")
        return True

    def listen(self):
        """
        Starts the main event listening loop. This is a long-running process.
        It polls the blockchain for new 'TokensLocked' events.
        """
        if not self._setup():
            self.logger.critical("Failed to complete initial setup. Aborting listener.")
            return

        try:
            # Determine the starting block for the filter.
            # In a production system, you would persist the last processed block.
            start_block = self.source_connector.get_latest_block_number() - 100
            self.logger.info(f"Starting to listen for events from block {start_block}...")

            # Create an event filter for the 'TokensLocked' event.
            event_filter = self.source_contract.events.TokensLocked.create_filter(
                fromBlock=start_block
            )

            while self.is_running:
                try:
                    new_events = event_filter.get_new_entries()
                    if not new_events:
                        self.logger.debug(f"No new events found. Polling again in {self.poll_interval}s.")
                    else:
                        self.logger.info(f"Found {len(new_events)} new 'TokensLocked' event(s)!")
                        for event in new_events:
                            self._log_event_details(event)
                            self.event_processor.process_and_notify(event, self.source_connector.chain_name)

                    time.sleep(self.poll_interval)

                except Exception as loop_error:
                    # Handle transient errors inside the loop without crashing the service
                    self.logger.error(f"An error occurred in the listening loop: {loop_error}")
                    self.logger.info("Attempting to recover and continue...")
                    time.sleep(self.poll_interval * 2) # Longer sleep after an error

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received. Shutting down gracefully...")
            self.shutdown()
        except Exception as e:
            self.logger.critical(f"A fatal error occurred: {e}", exc_info=True)
            self.shutdown()

    def _log_event_details(self, event: Dict[str, Any]):
        """Helper method to log event details in a readable format."""
        args = event.get('args', {})
        details = (
            f"Event: {event.get('event')} | "
            f"Tx: {event.get('transactionHash', b'').hex()} | "
            f"Block: {event.get('blockNumber')} | "
            f"Sender: {args.get('sender')} | "
            f"Recipient: {args.get('recipient')} | "
            f"Amount: {args.get('amount')} | "
            f"Nonce: {args.get('nonce')}"
        )
        self.logger.info(details)

    def shutdown(self):
        """Performs cleanup actions before the script exits."""
        self.is_running = False
        self.logger.info("ONE2U Event Listener has been shut down.")


if __name__ == '__main__':
    # Entry point of the script.
    listener = CrossChainEventListener()
    listener.listen()
