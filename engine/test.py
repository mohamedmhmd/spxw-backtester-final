"""
IBKR Iron Condor Diagnostic - FIXED VERSION

Fixed:
- Uses random client ID to avoid conflicts
- Better connection verification
- Handles disconnection gracefully
"""

import asyncio
import logging
import random
from datetime import datetime, date

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_iron_condor_sync():
    """
    Test Iron Condor using SYNCHRONOUS approach.
    This avoids async issues and matches how ib_insync is typically used.
    """
    
    print("=" * 70)
    print("IBKR IRON CONDOR DIAGNOSTIC (SYNC VERSION)")
    print("=" * 70)
    
    # Import
    print("\n[1] Importing ib_insync...")
    try:
        from ib_insync import IB, Option, Index, Contract, ComboLeg, LimitOrder, util
        print("    ✅ Imported")
    except ImportError as e:
        print(f"    ❌ Import failed: {e}")
        return
    
    # Use random client ID to avoid conflicts
    client_id = random.randint(100, 999)
    print(f"\n[2] Using client ID: {client_id}")
    
    # Connect
    print("\n[3] Connecting to IBKR...")
    ib = IB()
    
    # Add disconnect handler
    def on_disconnected():
        print("    ⚠️ DISCONNECTED EVENT FIRED!")
    
    def on_error(reqId, errorCode, errorString, contract):
        print(f"    ⚠️ ERROR: reqId={reqId}, code={errorCode}, msg={errorString}")
    
    ib.disconnectedEvent += on_disconnected
    ib.errorEvent += on_error
    
    ports = [
        (7497, "TWS Paper"),
        (7496, "TWS Live"),
        (4002, "Gateway Paper"),
        (4001, "Gateway Live"),
    ]
    
    connected = False
    for port, desc in ports:
        try:
            print(f"    Trying {desc} (port {port})...")
            ib.connect('127.0.0.1', port, clientId=client_id, timeout=10)
            print(f"    ✅ Connected to {desc}")
            connected = True
            break
        except Exception as e:
            print(f"    ❌ Failed: {e}")
    
    if not connected:
        print("\n    ❌ Could not connect to any IBKR instance!")
        print("    Check:")
        print("    - TWS/Gateway is running")
        print("    - API is enabled in settings")
        print("    - No other app using same client ID")
        return
    
    # Verify connection
    print("\n[4] Verifying connection...")
    print(f"    isConnected(): {ib.isConnected()}")
    
    if not ib.isConnected():
        print("    ❌ Connection lost immediately!")
        return
    
    # Sleep to let connection stabilize
    print("    Waiting for connection to stabilize...")
    ib.sleep(2)
    
    print(f"    isConnected() after sleep: {ib.isConnected()}")
    
    if not ib.isConnected():
        print("    ❌ Connection dropped!")
        print("    This usually means:")
        print("    - Another app disconnected us (client ID conflict)")
        print("    - TWS rejected the connection")
        print("    - Check TWS API settings: 'Allow connections from localhost only'")
        return
    
    # Get accounts
    accounts = ib.managedAccounts()
    print(f"    Accounts: {accounts}")
    
    # Get SPX price
    print("\n[5] Getting SPX price...")
    try:
        spx_index = Index('SPX', 'CBOE')
        ib.qualifyContracts(spx_index)
        
        ib.reqMarketDataType(4)  # Use delayed data if no subscription
        
        ticker = ib.reqTickers(spx_index)[0]
        ib.sleep(2)
        
        spx_price = ticker.marketPrice()
        if not spx_price or spx_price != spx_price:  # Check for NaN
            spx_price = ticker.close
        if not spx_price or spx_price != spx_price:
            spx_price = ticker.last
        if not spx_price or spx_price != spx_price:
            spx_price = 6000.0
            print(f"    ⚠️ Using fallback price: {spx_price}")
        else:
            print(f"    ✅ SPX price: {spx_price}")
    except Exception as e:
        print(f"    ⚠️ Price error: {e}")
        spx_price = 6000.0
        print(f"    Using fallback: {spx_price}")
    
    # Check connection again
    if not ib.isConnected():
        print("\n    ❌ Connection lost during price fetch!")
        return
    
    # Calculate strikes
    print("\n[6] Calculating Iron Condor strikes...")
    
    atm_strike = round(spx_price / 5) * 5
    wing_width = 25
    
    strikes = {
        'long_put': atm_strike - wing_width,
        'short_put': atm_strike,
        'short_call': atm_strike,
        'long_call': atm_strike + wing_width,
    }
    
    print(f"    ATM: {atm_strike}")
    print(f"    Long Put:   {strikes['long_put']}")
    print(f"    Short Put:  {strikes['short_put']}")
    print(f"    Short Call: {strikes['short_call']}")
    print(f"    Long Call:  {strikes['long_call']}")
    
    # Expiry
    expiry = date.today().strftime('%Y%m%d')
    print(f"    Expiry: {expiry}")
    
    # Create contracts
    print("\n[7] Creating option contracts...")
    
    # Try SPX first, then SPXW
    for symbol in ['SPX', 'SPXW']:
        print(f"\n    Trying {symbol}...")
        
        leg_contracts = {}
        for leg_type in ['long_put', 'short_put', 'short_call', 'long_call']:
            strike = strikes[leg_type]
            right = 'P' if 'put' in leg_type else 'C'
            
            opt = Option(
                symbol=symbol,
                lastTradeDateOrContractMonth=expiry,
                strike=float(strike),
                right=right,
                exchange='SMART',
                currency='USD',
                multiplier='100'
            )
            leg_contracts[leg_type] = opt
        
        # Qualify
        print(f"    Qualifying {symbol} contracts...")
        
        if not ib.isConnected():
            print("    ❌ Connection lost before qualification!")
            return
        
        try:
            all_opts = list(leg_contracts.values())
            qualified = ib.qualifyContracts(*all_opts)
            
            qualified_count = sum(1 for opt in all_opts if opt.conId > 0)
            print(f"    Qualified: {qualified_count}/4")
            
            for leg_type, opt in leg_contracts.items():
                status = "✅" if opt.conId > 0 else "❌"
                print(f"      {status} {leg_type}: conId={opt.conId}, local={opt.localSymbol}")
            
            if qualified_count == 4:
                print(f"\n    ✅ {symbol} contracts qualified!")
                break
            else:
                print(f"    {symbol} failed, trying next...")
                
        except Exception as e:
            print(f"    ❌ Qualification error: {e}")
            if "Not connected" in str(e):
                print("    Connection was lost!")
                return
    else:
        print("\n    ❌ Could not qualify contracts with SPX or SPXW")
        ib.disconnect()
        return
    
    # Build combo
    print("\n[8] Building combo order...")
    
    legs = []
    for leg_type, opt in leg_contracts.items():
        action = 'SELL' if 'short' in leg_type else 'BUY'
        leg = ComboLeg(
            conId=opt.conId,
            ratio=1,
            action=action,
            exchange='SMART'
        )
        legs.append(leg)
        print(f"    {action} {opt.localSymbol}")
    
    combo = Contract(
        symbol=symbol,  # Use whichever symbol worked
        secType='BAG',
        exchange='SMART',
        currency='USD',
        comboLegs=legs
    )
    
    # Create order
    print("\n[9] Creating order...")
    
    test_price = 0.10  # Low price, won't fill
    
    order = LimitOrder(
        action='SELL',
        totalQuantity=1,
        lmtPrice=test_price,
        tif='DAY'
    )
    
    print(f"    SELL 1 Iron Condor @ ${test_price}")
    
    # Place order
    print("\n[10] Placing order...")
    
    proceed = input("    Place order? (y/n): ").strip().lower()
    if proceed != 'y':
        print("    Skipped.")
        ib.disconnect()
        return
    
    if not ib.isConnected():
        print("    ❌ Connection lost before order!")
        return
    
    try:
        trade = ib.placeOrder(combo, order)
        
        print(f"    Order ID: {trade.order.orderId}")
        
        # Wait for status
        ib.sleep(3)
        
        print(f"    Status: {trade.orderStatus.status}")
        
        if trade.log:
            print("    Log:")
            for entry in trade.log[-5:]:
                print(f"      {entry}")
        
        if trade.orderStatus.status in ['Submitted', 'PreSubmitted', 'PendingSubmit']:
            print("\n    ✅ ORDER PLACED SUCCESSFULLY!")
            print("    Check TWS Orders window.")
            
            cancel = input("\n    Cancel test order? (y/n): ").strip().lower()
            if cancel == 'y':
                ib.cancelOrder(trade.order)
                ib.sleep(1)
                print(f"    Cancelled. Status: {trade.orderStatus.status}")
        
        elif trade.orderStatus.status == 'Inactive':
            print("\n    ⚠️ Order REJECTED (Inactive)")
            print("    Check TWS Messages (Ctrl+M)")
        
        else:
            print(f"\n    Status: {trade.orderStatus.status}")
            
    except Exception as e:
        print(f"    ❌ Order error: {e}")
        import traceback
        traceback.print_exc()
    
    # Cleanup
    print("\n[11] Disconnecting...")
    ib.disconnect()
    print("    Done.")
    
    print("\n" + "=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    test_iron_condor_sync()