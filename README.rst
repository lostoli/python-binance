=========================
Welcome to python-binance
=========================

This is an unofficial Python wrapper for the `Binance exchange REST API v1/3 <https://github.com/binance-exchange/binance-official-api-docs>`_. I am in no way affiliated with Binance. Use at your own risk.

If you came here looking for the `Binance exchange <https://www.binance.com/?ref=10099792>`_ to purchase cryptocurrencies, then `go here <https://www.binance.com/?ref=10099792>`_. If you want to automate interactions with Binance stick around.

Make sure you update often and check the Changelog for new features and bug fixes.

Features
--------

- Implementation of all General, Market Data, and Account endpoints.
- Simple handling of authentication.
- No need to generate timestamps yourself—the wrapper does it for you.
- Response exception handling.
- Websocket handling with reconnection and multiplexed connections.
- Symbol Depth Cache.
- Historical Kline/Candle fetching function.
- Withdraw functionality.
- Deposit addresses.

This Fork
---------

This fork features numerous improvements on the parent project, though it is
still a work in progress. Specifically, migration to coroutine-based
websockets is not complete, though the parts that /are/ done are ready to use.
Everything outside of websockets is complete though, which is to say at least
as complete as the parent project. Among these improvements:

- A Binance account and API key are no longer needed for all API calls that do
  not require them.
- Compatibility with all deprecated versions of python has been removed, thus
  dramatically simplifying maintenance and increasing robustness.
- Unnecessary dependencies like dateparser are removed.
- Symbol names are made sensible. (The redundant and highly irritating get\_
  before every method name in binance.Client has been removed for instance.)
- Many many constants useful for interaction with the API (error messages,
  JSON dictionary key names, error codes, etc.) are added and those constants
  that were already present are more sensibly organised.
- Migration toward a coroutine-based websocket framework called websockets and
  away from the car fire that is twisted has begun.
- New convenience methods have been added to binance.Client.

For all changes, just look at the git history.

Quick Start
-----------

`Register an account with Binance <https://www.binance.com/register.html?ref=10099792>`_.

`Generate an API Key <https://www.binance.com/userCenter/createApi.html>`_ and assign relevant permissions.

.. code:: bash

    % pacaur -S python-binance-git


.. code:: python

    from binance import Client
    import binance.constants as bc
    client = Client(api_key, api_secret)

    # Get market depth.
    depth = client.order_book(symbol='BNBBTC')

    # Place a test market buy order. To place an actual order use the
    # create_order function.
    order = client.create_test_order(
        symbol='BNBBTC',
        side=bc.SIDE_BUY,
        type=bc.ORDER_TYPE_MARKET,
        quantity=100)

    # Get all symbol prices.
    prices = client.all_tickers()

    # Withdraw 100 ETH. Check docs for assumptions around withdrawals.
    from binance.exceptions import APIException, WithdrawException
    try:
        result = client.withdraw(
            asset='ETH',
            address='<eth_address>',
            amount=100)
    except APIException as e:
        print(e)
    except WithdrawException as e:
        print(e)
    else:
        print("Success")

    # Fetch list of withdrawals.
    withdraws = client.withdraw_history()

    # Fetch list of ETH withdrawals.
    eth_withdraws = client.withdraw_history(asset='ETH')

    # Get a deposit address for BTC.
    address = client.deposit_address(asset='BTC')

    # Start aggregated trade websocket for BNBBTC.
    def process_message(msg):
        print("message type: {}".format(msg['e']))
        print(msg)
        # do something

    from binance.websockets import SocketManager
    bm = SocketManager(client)
    bm.start_aggtrade_socket('BNBBTC', process_message)
    bm.start()

    # Get historical kline data from any date range.

    # Fetch 1 minute klines from one day ago until now.
    from datetime import datetime, timedelta
    from time import time
    klines = client.historical_klines("BNBBTC", bc.KLINE_INTERVAL_1MINUTE,
            datetime.utcnow() - timedelta(1))

    # Fetch 30 minute klines for the last month of 2017.
    klines = client.historical_klines("ETHBTC", bc.KLINE_INTERVAL_30MINUTE,
            datetime(2017, 12, 1), datetime(2018, 1, 1))

    # Fetch weekly klines since it listed.
    klines = client.historical_klines("NEOBTC", bc.KLINE_INTERVAL_1WEEK,
            datetime(2017, 1, 1))
