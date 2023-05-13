import threading
import requests
import json

from flask import Flask
from datetime import datetime
from web3 import Web3
from web3.contract import Contract

# Shared variables for returning from endpoints
shared_value = ""
shared_addressCandidates = ""
shared_addressesMonitored = ""

# Shared config
addressesToMonitor = []
addressesToMonitorLastTrade = {}

etherscanAPI = "XXX"
infuraAPI = "XXX"

cachedABIs = {}
lastBlock = 17251982 # 17251967

# Stats
stats = { 
            "ignoredTx" : 0,
            "candidateTx" : 0
        }

def refreshRecentTradesSince(addresses, last_seen_trades):
    # 1inch API endpoint
    url = f"https://api.1inch.exchange/v3.0/1/swap/user"

    updated_trades = {}

    for address in addresses:
        print("Refreshing trades for [" + str(address) + "]..")
        # Get the last seen trade for the address
        last_seen_trade = last_seen_trades.get(address)

        # Parameters for the request
        params = {
            "fromDate": last_seen_trade or "0",
            "toDate": "9999999999",
            "from": address,
            "size": 10  # Number of recent trades to retrieve for each address
        }

        # Make the GET request
        response = requests.get(url, params=params)

        # Check the response status
        if response.status_code == 200:
            trades = response.json()["transactions"]

            # If there are new trades, update the last seen trade
            if trades:
                last_trade = trades[-1]
                updated_trades[address] = last_trade["date"]

            # Process the trades as needed
            for trade in trades:
                # Do something with the trade data
                print(trade)
        else:
            print(f"Error retrieving recent trades for address: {address}")
            print(response)

    return updated_trades

def getABI(contractAddress):
    abi = ""
    if contractAddress in cachedABIs:
        #print("Sourcing ABI for [" + contractAddress + "] from cache")
        abi = cachedABIs[contractAddress]
    else:
        print("Getting ABI for [" + contractAddress + "] ..")
        abi_endpoint = "https://api.etherscan.io/api?module=contract&action=getabi&address=" + contractAddress + "&apikey=" + etherscanAPI
        try:
            abi_response = requests.get(abi_endpoint).text
            abijson = json.loads(abi_response)
            if abijson["status"] != "1" or abijson["message"] != "OK":
                print("Failed to get ABI for [" + contractAddress + "] reason [" + abijson["result"] + "]")
                return [False,""]
            abi = abijson["result"]
            cachedABIs[contractAddress] = abi
        except(...):
            print("Failed to get ABI for [" + contractAddress + "]")
            return [False,""]
    return [True,abi]

def refreshRecentTradesOnchain(addresses, last_seen_trades):
    # Connect to Ethereum using a provider URL
    web3 = Web3(Web3.HTTPProvider('https://mainnet.infura.io/v3/' + infuraAPI))

    # Retrieve the latest block number
    latest_block_number = web3.eth.get_block('latest')['number']

    global lastBlock
    if lastBlock == 0:
        # Just get the last block..
        lastBlock = latest_block_number - 1

    trades = []

    while lastBlock < latest_block_number + 1:
        print("Checking block [" + str(lastBlock) + "] to [" + str(latest_block_number) + "] ...")
        # Get the transactions involving the address
        block = web3.eth.get_block(block_identifier=lastBlock, full_transactions=True)
        txs = block["transactions"]
        
        for tx in txs:
            txFromAddress = tx["from"]
            if txFromAddress not in addresses:
                #print("Ignored tx from address [" + txFromAddress + "]")
                stats["ignoredTx"] = stats["ignoredTx"] + 1
                #continue

            stats["candidateTx"] = stats["candidateTx"] + 1
            
            contractAddress = tx['to']

            if contractAddress != "0x1111111254EEB25477B68fb85Ed929f73A960582":
                #print("Ignored tx due to wrong contract")
                continue
            
            # Since this user is interesting to us, try to get the ABI of the contract
            result, abi = getABI(contractAddress)
            if result == False:
                continue

            contract = web3.eth.contract(address=contractAddress, abi=abi)
            func_obj, txparams = contract.decode_function_input(tx["input"])

            if "desc" not in txparams or "srcToken" not in txparams["desc"] or "dstToken" not in txparams["desc"]:
                if "order" in txparams or "amount" in txparams:
                    print("Skipping limit order tx..")
                elif "srcToken" in txparams:
                    print("Skipping simple order tx.. TODO - may need to be checked")
                else:
                    print("Skipping tx as unexpected structure..")
                    print(txparams)
                continue

            srcTokenAddress = txparams["desc"]["srcToken"]
            srcTokenName = ""
            srcTokenSymbol = ""
            if srcTokenAddress != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
                result, srcabi = getABI(srcTokenAddress)
                if result == False:
                    print("Failed to get src token ABI!")
                    continue

                srcTokenContract = web3.eth.contract(srcTokenAddress , abi = srcabi)
                if "name" in srcTokenContract.functions and "symbol" in srcTokenContract.functions:
                    srcTokenName = srcTokenContract.functions.name().call() 
                    srcTokenSymbol = srcTokenContract.functions.symbol().call() 
                else:
                    print("Failed to extract token name")
                    continue
            else:
                srcTokenName = "Ether"
                srcTokenSymbol = "ETH"

            dstTokenAddress = txparams["desc"]["dstToken"]
            dstTokenName = ""
            dstTokenSymbol = ""
            if dstTokenAddress != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
                result, dstabi = getABI(dstTokenAddress)
                if result == False:
                    print("Failed to get dst token ABI!")
                    continue

                dstTokenContract = web3.eth.contract(dstTokenAddress , abi = dstabi)
                if "name" in dstTokenContract.functions and "symbol" in dstTokenContract.functions:
                    dstTokenName = dstTokenContract.functions.name().call() 
                    dstTokenSymbol = dstTokenContract.functions.symbol().call() 
                else:
                    print("Failed to extract token name")
                    continue
            else:
                dstTokenName = "Ethereum"
                dstTokenSymbol = "ETH"
            

            print("== Swap from [" + srcTokenName + "] [" + srcTokenSymbol + "] => [" + dstTokenName + "] [" + dstTokenSymbol + "]")

            # Sourcing ABI for [0x1111111254EEB25477B68fb85Ed929f73A960582] from cache
            # {'srcToken': '0xb794Ad95317f75c44090f64955954C3849315fFe', 
            # 'amount': 123245365836168002646841491456, 
            # 'minReturn': 2064598069515467915, 
            # 'pools': [28948022309329048857349863385047695461982394024809266214477451752942157778725]}

            #print(txparams)

            # detect whether this 
            #if 'amountIn' in txparams:


            # Filter and process the transactions to identify trades
            #print(trade_info)
            #trades.append(trade_info)
        lastBlock = lastBlock + 1

    return trades

def refreshRecentTrades():
    print("Refreshing trades for [" + str(len(addressesToMonitor)) + "] addresses..")
    #newTrades = refreshRecentTradesSince(addressesToMonitor, addressesToMonitorLastTrade)
    newTrades = refreshRecentTradesOnchain(addressesToMonitor, addressesToMonitorLastTrade)

    for trade in newTrades:
        # TODO check market and who is monitoring
        # TODO trigger trade event if needed
        print("New trade : " + str(trade))

    # Update debug status
    global shared_addressesMonitored
    shared_addressesMonitored = str(addressesToMonitorLastTrade)

def updateAddressCandidates():
    global shared_addressCandidates
    shared_addressCandidates = ""

def populateAddressWatchlist():
    # TODO get from contract

    # Sample addresses from https://etherscan.io/address/1inch.eth
    global addressesToMonitor
    addressesToMonitor = ["0x2119131ddc4c6f9f0c3924117d59df999426fc4d", "0x86Ab1098945C2501dA6219FF55cE2b181159Eea2"]

    for address in addressesToMonitor:
        # TODO last seen time should be correct, currently
        # this will always refresh from the start of history
        addressesToMonitorLastTrade[address] = 0

    print("Watching [" + str(len(addressesToMonitor)) + "] addresses")

    global shared_addressesMonitored
    shared_addressesMonitored = str(addressesToMonitorLastTrade)

# Function to continuously update the shared variable
def processingThread():
    global shared_value

    print("Getting addresses to watch..")
    populateAddressWatchlist()

    while True:
        print("Processing loop..")
        # Trigger candidate updates
        #updateAddressCandidates()

        # Trigger follow trade catch up
        refreshRecentTrades()

        current_time = datetime.now()
        current_time_string = current_time.strftime("%Y-%m-%d %H:%M:%S")
        shared_value = "Threading test " + str(current_time_string)

        # Sleep for some time
        threading.Event().wait(60)

# Create a Flask app
app = Flask(__name__)

# HTTP GET endpoint
@app.route('/')
def get_shared_variable():
    return shared_value

@app.route('/api/getFollowCandidates')
def getFollowCandidates():
    return shared_addressCandidates

@app.route('/api/getAddressesMonitored')
def getAddressesMonitored():
    return shared_addressesMonitored

if __name__ == '__main__':
    # Start the shared variable update thread
    update_thread = threading.Thread(target=processingThread)
    update_thread.daemon = True
    update_thread.start()

    # Start the Flask web server
    app.run()
