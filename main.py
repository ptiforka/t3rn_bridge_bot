import time
from eth_abi import encode
import random
from web3 import Web3
from config import (
    PRIVATE_KEY,
    ARBITRUM_RPC,
    BASE_RPC,
    GAS_LIMIT,
    ARB_TO_BASE_CONTRACT,
    BASE_TO_ARB_CONTRACT,
    ARB_TO_BASE_DATA,
    BASE_TO_ARB_DATA,
    BRIDGE_AMOUNT_ETH,
    MIN_BALANCE_ETH
)

def get_web3(rpc_url: str) -> Web3:
    """Create and return a Web3 instance for the given RPC URL."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to {rpc_url}")
    return w3

def check_balance(w3: Web3, address: str) -> float:
    """Return the ETH balance of the address (in ETH)."""
    balance_wei = w3.eth.get_balance(address)
    return float(w3.from_wei(balance_wei, "ether"))

def build_tx(w3: Web3, wallet_address: str, to_addr: str, data: str, amount_eth: float) -> dict:
    """Construct a transaction dictionary for bridging, with gas estimation and fallback."""
    nonce = w3.eth.get_transaction_count(wallet_address)
    gas_price = w3.eth.gas_price
    tx = {
        "to": Web3.to_checksum_address(to_addr),
        "from": wallet_address,
        "value": w3.to_wei(amount_eth, "ether"),
        "data": data,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    }

    try:
        estimated_gas = w3.eth.estimate_gas(tx)
        gas_limit = int(estimated_gas * 1.2)  # Add a buffer (20%)
        print(f"Estimated gas: {estimated_gas}, using gas limit: {gas_limit}")
    except Exception as e:
        print(f"Gas estimation failed: {e}")
        gas_limit = GAS_LIMIT  # Fallback
        print(f"Using fallback gas limit: {gas_limit}")

    tx["gas"] = gas_limit
    return tx


def send_tx(w3: Web3, tx: dict, private_key: str):
    """Sign, send the transaction, and wait for the receipt."""
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"TX sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    status = "SUCCESS" if receipt.status == 1 else "FAIL"
    print(f"{status} in block {receipt.blockNumber}")
    return receipt

def decode_revert_reason(w3: Web3, contract_addr: str, from_addr: str, data: str, amount_eth: float):
    """
    Attempt an eth_call to get the revert reason.
    Uncomment and use this function to troubleshoot failed transactions.
    """
    call_tx = {
        "to": Web3.to_checksum_address(contract_addr),
        "from": from_addr,
        "value": w3.to_wei(amount_eth, "ether"),
        "data": data,
    }
    try:
        w3.eth.call(call_tx, "latest")
        print("No revert reason (simulation success).")
    except Exception as e:
        print(f"Revert reason: {e}")

def bridge_arb_to_base(w3_arb: Web3, wallet_addr: str, private_key: str):
    """Send BRIDGE_AMOUNT_ETH from Arbitrum to Base."""
    tx = build_tx(w3_arb, wallet_addr, ARB_TO_BASE_CONTRACT, ARB_TO_BASE_DATA, BRIDGE_AMOUNT_ETH)
    return send_tx(w3_arb, tx, private_key)

def bridge_base_to_arb(w3_base: Web3, wallet_addr: str, private_key: str):
    """Send BRIDGE_AMOUNT_ETH from Base to Arbitrum."""
    tx = build_tx(w3_base, wallet_addr, BASE_TO_ARB_CONTRACT, BASE_TO_ARB_DATA, BRIDGE_AMOUNT_ETH)
    return send_tx(w3_base, tx, private_key)

def verify_contract_code(w3: Web3, address: str, network_name: str):
    code = w3.eth.get_code(Web3.to_checksum_address(address))
    if code == b'':
        print(f"❌ No contract found at {address} on {network_name}")
    else:
        print(f"✅ Contract exists at {address} on {network_name} (code length: {len(code)} bytes)")

def main_loop():
    w3_arb = get_web3(ARBITRUM_RPC)
    w3_base = get_web3(BASE_RPC)

    verify_contract_code(w3_arb, ARB_TO_BASE_CONTRACT, "Arbitrum Sepolia")
    verify_contract_code(w3_base, BASE_TO_ARB_CONTRACT, "Base Sepolia")

    wallet = w3_arb.eth.account.from_key(PRIVATE_KEY)
    address = wallet.address
    print(f"\nUsing wallet: {address}")

    while True:
        try:
            bal_arb = check_balance(w3_arb, address)
            bal_base = check_balance(w3_base, address)
            print(f"\nArbitrum ETH: {bal_arb:.4f}, Base ETH: {bal_base:.4f}")

            # If both chains are below the minimum threshold, wait and retry
            if bal_arb < MIN_BALANCE_ETH and bal_base < MIN_BALANCE_ETH:
                print(f"Both chains under {MIN_BALANCE_ETH} ETH; waiting 30s ...")
                time.sleep(30)
                continue

            # Bridge from Arbitrum to Base while there is enough ETH on Arbitrum
            while check_balance(w3_arb, address) >= MIN_BALANCE_ETH:
                print("Bridging ARB -> BASE ...")
                # Uncomment the following line to decode the revert reason for troubleshooting:
                # decode_revert_reason(w3_arb, ARB_TO_BASE_CONTRACT, address, ARB_TO_BASE_DATA, BRIDGE_AMOUNT_ETH)
                bridge_arb_to_base(w3_arb, address, PRIVATE_KEY)
                delay = random.randint(10, 30)
                print(f"Waiting {delay} seconds before next ARB->BASE transaction...\n")
                time.sleep(delay)

            # Bridge from Base to Arbitrum while there is enough ETH on Base
            while check_balance(w3_base, address) >= MIN_BALANCE_ETH:
                print("Bridging BASE -> ARB ...")
                # Uncomment the following line to decode the revert reason for troubleshooting:
                # decode_revert_reason(w3_base, BASE_TO_ARB_CONTRACT, address, BASE_TO_ARB_DATA, BRIDGE_AMOUNT_ETH)
                bridge_base_to_arb(w3_base, address, PRIVATE_KEY)
                delay = random.randint(10, 30)
                print(f"Waiting {delay} seconds before next BASE->ARB transaction...\n")
                time.sleep(delay)

            # If both balances drop below threshold, wait 60 seconds before rechecking
            print(f"Both chains below {MIN_BALANCE_ETH} ETH; waiting 60 seconds before rechecking...")
            time.sleep(60)

        except Exception as e:
            print(f"Error: {e}. Retrying in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    main_loop()
