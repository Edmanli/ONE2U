# ONE2U - Cross-Chain Event Listener Simulation

This repository contains a Python-based simulation of an event listener component for a cross-chain bridge. This script is designed to monitor a smart contract on a source blockchain (e.g., Ethereum) for specific events (e.g., `TokensLocked`), process them, and then simulate notifying a relayer service to complete the cross-chain action on a destination chain.

This project serves as an architectural blueprint for building robust, modular, and maintainable off-chain infrastructure for decentralized applications.

## Concept

In a typical cross-chain bridge, users lock assets on a source chain, which triggers the release or minting of corresponding assets on a destination chain. The bridge's security and liveness depend on a reliable off-chain system that can:

1.  **Listen** for `TokensLocked` events on the source chain's bridge contract.
2.  **Verify** the finality of these events.
3.  **Relay** a signed message to the destination chain's bridge contract.
4.  **Authorize** the release of tokens on the destination chain.

This script simulates step 1 and the initial part of step 3. It provides a foundational structure for a service that listens to on-chain events and triggers off-chain workflows.

## Code Architecture

The script is designed with a clear separation of concerns, using distinct classes for different functionalities. This makes the system easier to test, extend, and maintain.

-   `ConfigManager`:
    -   **Responsibility**: Manages all configuration, loading sensitive data like RPC URLs and contract addresses from a `.env` file. This avoids hardcoding secrets in the source code.
    -   **Rationale**: Centralizes configuration management and promotes best practices for handling secrets.

-   `BlockchainConnector`:
    -   **Responsibility**: Encapsulates all interactions with a single blockchain via `web3.py`. It handles establishing a connection, retrying on failure, and instantiating contract objects.
    -   **Rationale**: Isolates blockchain-specific logic, allowing the main application to be agnostic about the underlying `web3` implementation. We can easily swap out `Web3.HTTPProvider` for `WebsocketProvider` here without changing other parts of the code.

-   `EventProcessor`:
    -   **Responsibility**: Takes raw event data, formats it into a standardized payload, and triggers the next step in the workflow. In this simulation, it makes an HTTP POST request to a mock relayer service using the `requests` library.
    -   **Rationale**: Decouples event detection from event handling. This class could be extended to include more complex logic like event validation, database logging, or queuing tasks in a message broker like RabbitMQ or Kafka.

-   `CrossChainEventListener`:
    -   **Responsibility**: The main orchestrator. It initializes and coordinates all the other components. It sets up the blockchain connection, creates the event filter, and runs the main polling loop.
    -   **Rationale**: Acts as the central nervous system of the application, defining the high-level business logic and lifecycle of the listener.

### Data Flow

1.  The `main` block initializes `CrossChainEventListener`.
2.  `CrossChainEventListener` uses `ConfigManager` to get configuration details.
3.  It then instantiates a `BlockchainConnector` to connect to the source chain.
4.  Once connected, it gets a `Contract` object and creates an event filter for the `TokensLocked` event.
5.  The `listen()` method starts a loop, periodically calling `filter.get_new_entries()`.
6.  When new events are found, they are passed to the `EventProcessor`.
7.  `EventProcessor` formats the data and makes an API call to the configured relayer endpoint.
8.  The loop continues until the script is manually stopped (e.g., with Ctrl+C), which triggers a graceful shutdown.

## How it Works

The script operates as a long-running service that continuously polls a blockchain node for new events.

1.  **Initialization**: On startup, the script loads its configuration from a `.env` file. This includes the RPC URL for the source chain, the address of the bridge contract to monitor, and the URL for the relayer service.

2.  **Connection**: It establishes a connection to the source chain's RPC endpoint. The connection logic includes a retry mechanism to handle transient network issues.

3.  **Filtering**: It creates a persistent filter on the bridge smart contract, specifically targeting the `TokensLocked` event. The filter starts from a recent block to avoid processing the entire chain history on every run.

4.  **Polling Loop**: The script enters an infinite loop. In each iteration, it:
    -   Queries the blockchain node for any new log entries matching the filter since the last poll.
    -   If new events are found, it iterates through each one.
    -   For each event, it logs the key details (transaction hash, sender, amount, etc.).
    -   It then passes the event to the `EventProcessor`.

5.  **Processing and Notification**: The `EventProcessor` transforms the event's data into a structured JSON payload and sends it to a pre-configured HTTP endpoint (the simulated relayer). This simulates informing the next part of the bridge infrastructure that a cross-chain transfer has been initiated.

6.  **Error Handling & Shutdown**: The script includes robust error handling for network failures, API issues, and invalid configurations. It can also be shut down gracefully using `Ctrl+C`, ensuring a clean exit.

## Usage Example

Follow these steps to set up and run the event listener simulation.

**1. Clone the Repository**

```bash
git clone <repository-url>
cd ONE2U
```

**2. Create a Virtual Environment**

It's highly recommended to use a virtual environment to manage dependencies.

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

**3. Install Dependencies**

Install the required Python libraries from the `requirements.txt` file.

```bash
pip install -r requirements.txt
```

**4. Create a `.env` Configuration File**

Create a file named `.env` in the root of the project directory and add the following content. You can get a free RPC URL from services like [Infura](https://infura.io) or [Alchemy](https://www.alchemy.com).

```dotenv
# RPC endpoint for the source blockchain (e.g., Ethereum Sepolia testnet)
SOURCE_CHAIN_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"

# Address of the deployed bridge contract on the source chain
SOURCE_CHAIN_BRIDGE_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890"

# Mock API endpoint for the relayer service. Use a service like Webhook.site to see the requests.
RELAYER_API_ENDPOINT="https://webhook.site/your-unique-uuid"

# (Optional) Polling interval in seconds. Defaults to 15.
POLL_INTERVAL=10
```

**Note**: Replace the placeholder values with your actual data. The `SOURCE_CHAIN_BRIDGE_CONTRACT_ADDRESS` can be any valid contract address that emits similar events for testing purposes, as the script won't crash if no events are found.

**5. Run the Script**

Execute the main script from your terminal.

```bash
python script.py
```

**6. Observe the Output**

The script will start logging its status to the console. You will see messages about successful connections and periodic polling.

```
2023-10-27 10:00:00,123 - INFO - [CrossChainEventListener] - Initializing ONE2U Cross-Chain Event Listener...
2023-10-27 10:00:01,456 - INFO - [BlockchainConnector] - Successfully connected to SOURCE_CHAIN (Chain ID: 11155111).
2023-10-27 10:00:01,457 - INFO - [CrossChainEventListener] - Setup complete. Ready to start listening for events.
2023-10-27 10:00:01,789 - INFO - [CrossChainEventListener] - Starting to listen for events from block 4850100...
2023-10-27 10:00:11,800 - DEBUG - [CrossChainEventListener] - No new events found. Polling again in 10.0s.
...
```

If the monitored contract emits a `TokensLocked` event while the script is running, you will see it being processed:

```
2023-10-27 10:05:22,100 - INFO - [CrossChainEventListener] - Found 1 new 'TokensLocked' event(s)!
2023-10-27 10:05:22,101 - INFO - [CrossChainEventListener] - Event: TokensLocked | Tx: 0x... | Block: 4850250 | Sender: 0x... | Recipient: 0x... | Amount: 1000000000000000000 | Nonce: 123
2023-10-27 10:05:22,102 - INFO - [EventProcessor] - Processing event 'TokensLocked' from transaction 0x...
2023-10-27 10:05:23,500 - INFO - [EventProcessor] - Successfully notified relayer. Status: 200, Response: {"status": "ok"}
```
