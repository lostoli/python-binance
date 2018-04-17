import hashlib
import hmac
import requests
import time
from operator import itemgetter
import random
import string
from copy import deepcopy
from collections import namedtuple
from math import floor, log10

from .helpers import interval_to_milliseconds
from .exceptions import APIException, ResponseException, WithdrawException, \
    NoAPIKeyException, NoAPISecretException
import binance.exceptions as bex
import binance.constants as bc


Precisions = namedtuple('Precisions',
        ['quote', 'base', 'price', 'lot'])

class Client:

    API_URL = 'https://api.binance.com/api'
    WITHDRAW_API_URL = 'https://api.binance.com/wapi'
    WEBSITE_URL = 'https://www.binance.com'
    PUBLIC_API_VERSION = 'v1'
    PRIVATE_API_VERSION = 'v3'
    WITHDRAW_API_VERSION = 'v3'

    def __init__(self, api_key=None, api_secret=None, requests_params=None):
        """Binance API Client constructor

        :param api_key: optional - API Key
        :type api_key: str.
        :param api_secret: optional - API Secret
        :type api_secret: str.
        :param requests_params: optional - Dictionary of requests params to use
        for all calls
        :type requests_params: dict.

        """

        self.API_KEY = api_key
        self.API_SECRET = api_secret
        self.session = self._init_session()
        self._requests_params = requests_params

        # init DNS and SSL cert
        self.ping()

    def _init_session(self):

        session = requests.session()
        session.headers.update({'Accept': 'application/json',
                                'User-Agent': 'binance/python'})
        if self.API_KEY:
            session.headers.update({'X-MBX-APIKEY': self.API_KEY})
        return session

    def _create_api_uri(self, path, signed=True, version=PUBLIC_API_VERSION):
        v = self.PRIVATE_API_VERSION if signed else version
        return '/'.join([self.API_URL, v, path])

    def _create_withdraw_api_uri(self, path):
        return '/'.join([
                self.WITHDRAW_API_URL, self.WITHDRAW_API_VERSION, path])

    def _create_website_uri(self, path):
        return self.WEBSITE_URL + '/' + path

    def _assert_api_key(self):
        if not self.API_KEY:
            raise NoAPIKeyException()

    def _generate_signature(self, data):
        if not self.API_SECRET:
            raise NoAPISecretException()

        ordered_data = self._order_params(data)
        query_string = '&'.join(
                ["{}={}".format(d[0], d[1]) for d in ordered_data])
        m = hmac.new(self.API_SECRET.encode('utf-8'),
                query_string.encode('utf-8'), hashlib.sha256)
        return m.hexdigest()

    def _order_params(self, data):
        """Convert params to list with signature as last element

        :param data:
        :return:

        """
        has_signature = False
        params = []
        for key, value in data.items():
            if key == 'signature':
                has_signature = True
            else:
                params.append((key, value))
        # Sort parameters by key.
        params.sort(key=itemgetter(0))
        if has_signature:
            params.append(('signature', data['signature']))
        return params

    def _request(self, method, uri, signed, force_params=False, retry=False,
            **kwargs):
        # Retry is meant to be used by the application to enable or disable
        # retrying. Only read-only stuff like queries should default to
        # retrying, and not stuff like order placement. Retrying for
        # remote state-modifying calls should be handled on a per-call basis.

        # Set default requests timeout.
        kwargs['timeout'] = 10

        # Add our global requests params.
        if self._requests_params:
            kwargs.update(self._requests_params)

        # kwargs gets changed every attempt, so remember the original kwargs.
        kwargs0 = kwargs
        while True:
            try:
                kwargs = deepcopy(kwargs0)

                if signed:
                    # Generate signature.
                    kwargs['data']['timestamp'] = int(time.time() * 1000)
                    kwargs['data']['signature'] = \
                            self._generate_signature(kwargs['data'])
                if 'data' in kwargs0:
                    # Find any requests params passed and apply them.
                    if 'requests_params' in kwargs['data']:
                        # Merge requests params into kwargs.
                        kwargs.update(kwargs['data']['requests_params'])
                        del(kwargs['data']['requests_params'])

                    # Sort get or post params to match signature order.
                    kwargs['data'] = self._order_params(kwargs['data'])

                    # If this is a get request, assign data array to params
                    # value for requests lib.
                    if method == 'get' or force_params:
                        kwargs['params'] = kwargs['data']
                        del(kwargs['data'])
                response = getattr(self.session, method)(uri, **kwargs)
                return self._handle_response(response)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout):
                if not retry:
                    # Error handling for these two cases is always the same, so
                    # merge the two cases into a single Binance connection
                    # error.  If I'm wrong, this can be changed back again.
                    raise bex.ConnectionError
            except APIException as e:
                # Ignore the lots and lots of spurious errors. This is the
                # one time retrying should always be attempted. This shouldn't
                # be a problem, but it is. God damn it, binance. Fix this.
                if e.code != bc.E_UNKNOWN and \
                        e.code != bc.E_INVALID_TIMESTAMP:
                    raise
            time.sleep(1)

    def _request_api(self, method, path, signed=False,
            version=PUBLIC_API_VERSION, **kwargs):
        uri = self._create_api_uri(path, signed, version)

        return self._request(method, uri, signed, **kwargs)

    def _request_withdraw_api(self, method, path, signed=False, **kwargs):
        uri = self._create_withdraw_api_uri(path)

        return self._request(method, uri, signed, True, **kwargs)

    def _request_website(self, method, path, signed=False, **kwargs):

        uri = self._create_website_uri(path)

        return self._request(method, uri, signed, **kwargs)

    def _handle_response(self, response):
        """Internal helper for handling API responses from the Binance server.
        Raises the appropriate exceptions when necessary; otherwise, returns
        the response.
        """
        if response.status_code // 100 != 2:
            raise APIException(response)
        try:
            return response.json()
        except ValueError:
            raise ResponseException(
                    'Invalid Response: {}'.format(response.text))

    def _get(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_api('get', path, signed, version, **kwargs)

    def _post(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_api('post', path, signed, version, **kwargs)

    def _put(self, path, signed=False, version=PUBLIC_API_VERSION, **kwargs):
        return self._request_api('put', path, signed, version, **kwargs)

    def _delete(self, path, signed=False,
            version=PUBLIC_API_VERSION, **kwargs):
        return self._request_api('delete', path, signed, version, **kwargs)

    # Exchange Endpoints

    def products(self):
        """Return list of products currently listed on Binance

        Use exchange_info() call instead

        :returns: list - List of product dictionaries

        :raises: ResponseException, APIException, ConnectionError

        """

        products = self._request_website('get', 'exchange/public/product')
        return products

    def exchange_info(self):
        """Return rate limits and list of symbols

        :returns: list - List of product dictionaries

        .. code-block:: python

            {
                "timezone": "UTC",
                "serverTime": 1508631584636,
                "rateLimits": [
                    {
                        "rateLimitType": "REQUESTS",
                        "interval": "MINUTE",
                        "limit": 1200
                    },
                    {
                        "rateLimitType": "ORDERS",
                        "interval": "SECOND",
                        "limit": 10
                    },
                    {
                        "rateLimitType": "ORDERS",
                        "interval": "DAY",
                        "limit": 100000
                    }
                ],
                "exchangeFilters": [],
                "symbols": [
                    {
                        "symbol": "ETHBTC",
                        "status": "TRADING",
                        "baseAsset": "ETH",
                        "baseAssetPrecision": 8,
                        "quoteAsset": "BTC",
                        "quotePrecision": 8,
                        "orderTypes": ["LIMIT", "MARKET"],
                        "icebergAllowed": false,
                        "filters": [
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.00000100",
                                "maxPrice": "100000.00000000",
                                "tickSize": "0.00000100"
                            }, {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.00100000",
                                "maxQty": "100000.00000000",
                                "stepSize": "0.00100000"
                            }, {
                                "filterType": "MIN_NOTIONAL",
                                "minNotional": "0.00100000"
                            }
                        ]
                    }
                ]
            }

        :raises: ResponseException, APIException, ConnectionError

        """

        return self._get('exchangeInfo', retry=True)

    def symbol_info(self, symbol=None):
        """Return information about a symbol

        :param symbol: e.g. BNBBTC. If unspecified, the symbol info of all
        symbols is returned in a dictionary.
        :type symbol: str

        :returns: Dict if found, None if not

        .. code-block:: python

            {
                "status": "TRADING",
                "baseAsset": "ETH",
                "baseAssetPrecision": 8,
                "quoteAsset": "BTC",
                "quotePrecision": 8,
                "orderTypes": ["LIMIT", "MARKET"],
                "icebergAllowed": false,
                "filters": {
                    "PRICE_FILTER": {
                        "minPrice": "0.00000100",
                        "maxPrice": "100000.00000000",
                        "tickSize": "0.00000100"
                    },
                    "LOT_SIZE": {
                        "minQty": "0.00100000",
                        "maxQty": "100000.00000000",
                        "stepSize": "0.00100000"
                    },
                    "MIN_NOTIONAL": {
                        "minNotional": "0.00100000"
                    }
                }
            }

        :raises: ResponseException, APIException, ConnectionError

        """

        res = self.exchange_info()

        sis = {}
        for si in res['symbols']:
            n = si.pop('symbol')
            si['filters'] = self.filters_as_dict(si['filters'])
            sis[n] = si

        if symbol is None:
            return sis
        else:
            return sis.get(symbol, None)
    @staticmethod
    def filters_as_dict(fs):
        fd = {}
        for f in fs:
            f = f.copy()
            t = f.pop('filterType')
            fd[t] = f
        return fd
    def symbol_filters(self, symbol):
        """Return a symbol's filters as a dictionary with the filterType as
        the key."""
        return self.symbol_info(symbol)['filters']

    def symbol_precisions(self, symbol=None):
        if symbol is not None:
            return Client.precisions_from_symbol_info(self.symbol_info(symbol))
        ps = {}
        for symbol, info in self.symbol_info().items():
            ps[symbol] = Client.precisions_from_symbol_info(info)
        return ps
    @staticmethod
    def precisions_from_symbol_info(i):
        def ndigits(stepstr):
            return floor(-log10(float(stepstr)))
        fd = i['filters']
        return Precisions(i['quotePrecision'], i['baseAssetPrecision'],
                ndigits(fd['PRICE_FILTER']['tickSize']),
                ndigits(fd['LOT_SIZE']['stepSize']))

    # General Endpoints

    def ping(self):
        """Test connectivity to the Rest API.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#test-connectivity

        :returns: Empty array

        .. code-block:: python

            {}

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ping')

    def server_time(self):
        """Test connectivity to the Rest API and get the current server time.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#check-server-time

        :returns: Current server time

        .. code-block:: python

            {
                "serverTime": 1499827319559
            }

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('time')

    # Market Data Endpoints

    def all_tickers(self):
        """Latest price for all symbols.

        https://www.binance.com/restapipub.html#symbols-price-ticker

        :returns: List of market tickers

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "price": "4.00000200"
                },
                {
                    "symbol": "ETHBTC",
                    "price": "0.07946600"
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ticker/allPrices')

    def orderbook_tickers(self):
        """Best price/qty on the order book for all symbols.

        https://www.binance.com/restapipub.html#symbols-order-book-ticker

        :returns: List of order book market entries

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "bidPrice": "4.00000000",
                    "bidQty": "431.00000000",
                    "askPrice": "4.00000200",
                    "askQty": "9.00000000"
                },
                {
                    "symbol": "ETHBTC",
                    "bidPrice": "0.07946700",
                    "bidQty": "9.00000000",
                    "askPrice": "100000.00000000",
                    "askQty": "1000.00000000"
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ticker/allBookTickers')

    def order_book(self, **params):
        """Get the Order Book for the market

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#order-book

        :param symbol: required
        :type symbol: str
        :param limit:  Default 100; max 100
        :type limit: int

        :returns: API response

        .. code-block:: python

            {
                "lastUpdateId": 1027024,
                "bids": [
                    [
                        "4.00000000",     # PRICE
                        "431.00000000",   # QTY
                        []                # Can be ignored
                    ]
                ],
                "asks": [
                    [
                        "4.00000200",
                        "12.00000000",
                        []
                    ]
                ]
            }

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('depth', data=params)

    def recent_trades(self, **params):
        """Get recent trades (up to last 500).

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#recent-trades-list

        :param symbol: required
        :type symbol: str
        :param limit:  Default 500; max 500.
        :type limit: int

        :returns: API response

        .. code-block:: python

            [
                {
                    "id": 28457,
                    "price": "4.00000100",
                    "qty": "12.00000000",
                    "time": 1499865549590,
                    "isBuyerMaker": true,
                    "isBestMatch": true
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('trades', data=params)

    def historical_trades(self, **params):
        """Get older trades.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#recent-trades-list

        :param symbol: required
        :type symbol: str
        :param limit:  Default 500; max 500.
        :type limit: int
        :param fromId:  TradeId to fetch from. Default gets most recent trades.
        :type fromId: str

        :returns: API response

        .. code-block:: python

            [
                {
                    "id": 28457,
                    "price": "4.00000100",
                    "qty": "12.00000000",
                    "time": 1499865549590,
                    "isBuyerMaker": true,
                    "isBestMatch": true
                }
            ]

        :raises: ResponseException, APIException, NoAPIKeyException,
        ConnectionError

        """
        self._assert_api_key()
        return self._get('historicalTrades', data=params)

    def aggregate_trades(self, **params):
        """Get compressed, aggregate trades. Trades that fill at the time,
        from the same order, with the same price will have the quantity
        aggregated.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#compressedaggregate-trades-list

        :param symbol: required
        :type symbol: str
        :param fromId:  ID to get aggregate trades from INCLUSIVE.
        :type fromId: str
        :param startTime: Timestamp in ms to get aggregate trades from
        INCLUSIVE.
        :type startTime: int
        :param endTime: Timestamp in ms to get aggregate trades until
        INCLUSIVE.
        :type endTime: int
        :param limit:  Default 500; max 500.
        :type limit: int

        :returns: API response

        .. code-block:: python

            [
                {
                    "a": 26129,         # Aggregate tradeId
                    "p": "0.01633102",  # Price
                    "q": "4.70443515",  # Quantity
                    "f": 27781,         # First tradeId
                    "l": 27781,         # Last tradeId
                    "T": 1498793709153, # Timestamp
                    "m": true,          # Was the buyer the maker?
                    "M": true           # Was the trade the best price match?
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('aggTrades', data=params, retry=True)

    def aggregate_trade_iter(self, pair, start_time=None, last_id=None):
        """Iterate over aggregate trade data from (start_time or last_id) to
        the end of the history so far.

        If start_time is specified, start with the first trade after
        start_time. Meant to initialise a local cache of trade data.

        If last_id is specified, start with the trade after it. This is meant
        for updating a pre-existing local trade data cache.

        Only allows start_time or last_id—not both. Not guaranteed to work
        right if you're running more than one of these simultaneously. You
        will probably hit your rate limit.

        :param start_time: UNIX timestamp in milliseconds. The iterator will
        return the first trade occurring later than this time.
        :type start_time: int
        :param last_id: aggregate trade ID of the last known aggregate trade.
        Not a regular trade ID. See
        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#compressedaggregate-trades-list.

        :returns: an iterator of JSON objects, one per trade. The format of
        each object is identical to Client.aggregate_trades().

        :type last_id: int
        """
        if start_time is not None and last_id is not None:
            raise ValueError(
                'start_time and last_id may not be simultaneously specified.')

        # If there's no last_id, get one.
        if last_id is None:
            # Without a last_id, we actually need the first trade.  Normally,
            # we'd get rid of it. See the next loop.
            if start_time is None:
                trades = self.aggregate_trades(symbol=pair, fromId=0)
            else:
                # It doesn't matter what the end time is, as long as it's less
                # than an hour and the result set contains at least one trade.
                # A half an hour should be fine most of the time, but just in
                # case there isn't a trade, we'll keep looking.
                dt = 1000*3600//2
                while True:
                    if start_time > time.time():
                        return
                    trades = self.aggregate_trades(symbol=pair,
                            startTime=start_time, endTime=start_time + dt)
                    if len(trades) > 0:
                        break
                    start_time += dt - 1000
            for t in trades:
                yield t
            last_id = trades[-1][bc.AGG_ID]

        while True:
            # There is no need to wait between queries, to avoid hitting the
            # rate limit. We're using blocking IO, and as long as we're the
            # only thread running calls like this, binance will automatically
            # add the right delay time on their end, forcing us to wait for
            # data. That really simplifies this function's job. Binance is
            # fucking awesome.
            trades = self.aggregate_trades(symbol=pair, fromId=last_id)
            # fromId=n returns a set starting with id n, but we already have
            # that one. So get rid of the first item in the result set.
            trades = trades[1:]
            if len(trades) == 0:
                return
            for t in trades:
                yield t
            last_id = trades[-1][bc.AGG_ID]

    def klines(self, **params):
        """Kline/candlestick bars for a symbol. Klines are uniquely identified
        by their open time.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#klinecandlestick-data

        :param symbol: required
        :type symbol: str
        :param interval: -
        :type interval: str
        :param limit: - Default 500; max 500.
        :type limit: int
        :param startTime:
        :type startTime: int
        :param endTime:
        :type endTime: int

        :returns: API response

        .. code-block:: python

            [
                [
                    1499040000000,      # Open time
                    "0.01634790",       # Open
                    "0.80000000",       # High
                    "0.01575800",       # Low
                    "0.01577100",       # Close
                    "148976.11427815",  # Volume
                    1499644799999,      # Close time
                    "2434.19055334",    # Quote asset volume
                    308,                # Number of trades
                    "1756.87402397",    # Taker buy base asset volume
                    "28.46694368",      # Taker buy quote asset volume
                    "17928899.62484339" # Can be ignored
                ]
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('klines', data=params)

    def historical_klines(self, symbol, interval, start, end=None):
        """Get Historical Klines from Binance

        See dateparse docs for valid start and end string formats
        http://dateparser.readthedocs.io/en/latest/

        If using offset strings for dates add "UTC" to date string e.g. "now
        UTC", "11 hours ago UTC"

        :param symbol: Name of symbol pair e.g BNBBTC
        :type symbol: str
        :param interval: Binance Kline interval
        :type interval: str
        :param start: Start datetime.
        :type start: datetime
        :param end: optional - end datetime.
        :type end: datetime

        :return: list of OHLCV values

        """
        # init our list
        output_data = []

        # setup the max limit
        limit = 500

        # convert interval to useful value in milliseconds
        timeframe = interval_to_milliseconds(interval)

        # convert our datetimes to milliseconds
        startTime = int(start.timestamp() * 1000)

        # if an end time was passed convert it
        endTime = None
        if end:
            endTime = int(end.timestamp() * 1000)

        idx = 0
        # it can be difficult to know when a symbol was listed on Binance so
        # allow start time to be before list date
        symbol_existed = False
        while True:
            # fetch the klines from startTime up to max 500 entries or the
            # endTime if set
            temp_data = self.klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                startTime=startTime,
                endTime=endTime
            )

            # handle the case where our start date is before the symbol pair
            # listed on Binance
            if not symbol_existed and len(temp_data):
                symbol_existed = True

            if symbol_existed:
                # append this loops data to our output data
                output_data += temp_data

                # update our start timestamp using the last value in the array
                # and add the interval timeframe
                startTime = temp_data[len(temp_data) - 1][0] + timeframe
            else:
                # it wasn't listed yet, increment our start date
                startTime += timeframe

            idx += 1
            # check if we received less than the required limit and exit the
            # loop
            if len(temp_data) < limit:
                # exit the while loop
                break

            # sleep after every 3rd call to be kind to the API
            if idx % 3 == 0:
                time.sleep(1)

        return output_data

    def ticker(self, **params):
        """24 hour price change statistics.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#24hr-ticker-price-change-statistics

        :param symbol:
        :type symbol: str

        :returns: API response

        .. code-block:: python

            {
                "priceChange": "-94.99999800",
                "priceChangePercent": "-95.960",
                "weightedAvgPrice": "0.29628482",
                "prevClosePrice": "0.10002000",
                "lastPrice": "4.00000200",
                "bidPrice": "4.00000000",
                "askPrice": "4.00000200",
                "openPrice": "99.00000000",
                "highPrice": "100.00000000",
                "lowPrice": "0.10000000",
                "volume": "8913.30000000",
                "openTime": 1499783499040,
                "closeTime": 1499869899040,
                "fristId": 28385,   # First tradeId
                "lastId": 28460,    # Last tradeId
                "count": 76         # Trade count
            }

        OR

        .. code-block:: python

            [
                {
                    "priceChange": "-94.99999800",
                    "priceChangePercent": "-95.960",
                    "weightedAvgPrice": "0.29628482",
                    "prevClosePrice": "0.10002000",
                    "lastPrice": "4.00000200",
                    "bidPrice": "4.00000000",
                    "askPrice": "4.00000200",
                    "openPrice": "99.00000000",
                    "highPrice": "100.00000000",
                    "lowPrice": "0.10000000",
                    "volume": "8913.30000000",
                    "openTime": 1499783499040,
                    "closeTime": 1499869899040,
                    "fristId": 28385,   # First tradeId
                    "lastId": 28460,    # Last tradeId
                    "count": 76         # Trade count
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ticker/24hr', data=params)

    def symbol_ticker(self, **params):
        """Latest price for a symbol or symbols.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#24hr-ticker-price-change-statistics

        :param symbol:
        :type symbol: str

        :returns: API response

        .. code-block:: python

            {
                "symbol": "LTCBTC",
                "price": "4.00000200"
            }

        OR

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "price": "4.00000200"
                },
                {
                    "symbol": "ETHBTC",
                    "price": "0.07946600"
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ticker/price', data=params,
                version=self.PRIVATE_API_VERSION)

    def orderbook_ticker(self, **params):
        """Latest price for a symbol or symbols.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#symbol-order-book-ticker

        :param symbol:
        :type symbol: str

        :returns: API response

        .. code-block:: python

            {
                "symbol": "LTCBTC",
                "bidPrice": "4.00000000",
                "bidQty": "431.00000000",
                "askPrice": "4.00000200",
                "askQty": "9.00000000"
            }

        OR

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "bidPrice": "4.00000000",
                    "bidQty": "431.00000000",
                    "askPrice": "4.00000200",
                    "askQty": "9.00000000"
                },
                {
                    "symbol": "ETHBTC",
                    "bidPrice": "0.07946700",
                    "bidQty": "9.00000000",
                    "askPrice": "100000.00000000",
                    "askQty": "1000.00000000"
                }
            ]

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._get('ticker/bookTicker', data=params,
                version=self.PRIVATE_API_VERSION)

    # Account Endpoints

    def create_order_raw(self, **params):
        """Send in a new order, the raw API call. If it fails due to network
        error, the order may have still gone through. If you don't want to
        handle this, use Client.create_order(). The only reason to use this is
        if you require transactTime in the result."""
        return self._post('order', True, data=params)
    def create_order(self, prefix='py_', **params):
        """Send in a new order.

        Occasionally the REST call fails due to network error, but the order
        has actually gone through. When this happens, the result of the
        original REST call is lost and the result of Client.query_order() is
        returned instead. It has all of the same information, except for
        transactTime. So don't rely on the presence of transactTime in the
        result!! If you need it, use Client.create_order_rest().

        Any order with an icebergQty MUST have timeInForce set to GTC.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#new-order--trade

        :param symbol: required
        :type symbol: str
        :param side: required
        :type side: str
        :param type: required
        :type type: str
        :param timeInForce: required if limit order
        :type timeInForce: str
        :param quantity: required
        :type quantity: decimal
        :param price: required
        :type price: str
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param icebergQty: Used with LIMIT, STOP_LOSS_LIMIT, and
        TAKE_PROFIT_LIMIT to create an iceberg order.
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        Response ACK:

        .. code-block:: python

            {
                "symbol":"LTCBTC",
                "orderId": 1,
                "clientOrderId": "myOrder1" # Will be newClientOrderId
                "transactTime": 1499827319559
            }

        Response RESULT:

        .. code-block:: python

            {
                "symbol": "BTCUSDT",
                "orderId": 28,
                "clientOrderId": "6gCrw2kRUAF9CvJDGP16IP",
                "transactTime": 1507725176595,
                "price": "0.00000000",
                "origQty": "10.00000000",
                "executedQty": "10.00000000",
                "status": "FILLED",
                "timeInForce": "GTC",
                "type": "MARKET",
                "side": "SELL"
            }

        Response FULL:

        .. code-block:: python

            {
                "symbol": "BTCUSDT",
                "orderId": 28,
                "clientOrderId": "6gCrw2kRUAF9CvJDGP16IP",
                "transactTime": 1507725176595,
                "price": "0.00000000",
                "origQty": "10.00000000",
                "executedQty": "10.00000000",
                "status": "FILLED",
                "timeInForce": "GTC",
                "type": "MARKET",
                "side": "SELL",
                "fills": [
                    {
                        "price": "4000.00000000",
                        "qty": "1.00000000",
                        "commission": "4.00000000",
                        "commissionAsset": "USDT"
                    },
                    {
                        "price": "3999.00000000",
                        "qty": "5.00000000",
                        "commission": "19.99500000",
                        "commissionAsset": "USDT"
                    },
                    {
                        "price": "3998.00000000",
                        "qty": "2.00000000",
                        "commission": "7.99600000",
                        "commissionAsset": "USDT"
                    },
                    {
                        "price": "3997.00000000",
                        "qty": "1.00000000",
                        "commission": "3.99700000",
                        "commissionAsset": "USDT"
                    },
                    {
                        "price": "3995.00000000",
                        "qty": "1.00000000",
                        "commission": "3.99500000",
                        "commissionAsset": "USDT"
                    }
                ]
            }

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, NoAPISecretException, ConnectionError

        """
        if 'newClientOrderId' not in params:
            s = ''
            for i in range(36 - len(prefix)):
                s += random.choice(string.ascii_letters + string.digits)
            params['newClientOrderId'] = prefix + s
        try:
            return self.create_order_raw(**params)
        except bex.ConnectionError:
            # The order may have gone through in spite of these errors! Try to
            # find it.
            for i in range(3):
                try:
                    return self.query_order(symbol=params['symbol'],
                            origClientOrderId=params['newClientOrderId'])
                except APIException as e:
                    if e.code != bc.E_NO_SUCH_ORDER:
                        raise
                except bex.ConnectionError:
                    pass
                time.sleep(1)
            raise

    def create_limit_order(self, timeInForce=bc.TIME_IN_FORCE_GTC, **params):
        """Send in a new limit order

        Any order with an icebergQty MUST have timeInForce set to GTC.

        :param symbol: required
        :type symbol: str
        :param side: required
        :type side: str
        :param quantity: required
        :type quantity: decimal
        :param price: required
        :type price: str
        :param timeInForce: default Good 'til cancelled
        :type timeInForce: str
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param icebergQty: Used with LIMIT, STOP_LOSS_LIMIT, and
        TAKE_PROFIT_LIMIT to create an iceberg order.
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'type': bc.ORDER_TYPE_LIMIT,
            'timeInForce': timeInForce
        })
        return self.create_order(**params)

    def create_limit_buy(self, timeInForce=bc.TIME_IN_FORCE_GTC, **params):
        """Send in a new limit buy order

        Any order with an icebergQty MUST have timeInForce set to GTC.

        :param symbol: required
        :type symbol: str
        :param quantity: required
        :type quantity: decimal
        :param price: required
        :type price: str
        :param timeInForce: default Good till cancelled
        :type timeInForce: str
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param stopPrice: Used with stop orders
        :type stopPrice: decimal
        :param icebergQty: Used with iceberg orders
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'side': bc.SIDE_BUY,
        })
        return self.create_limit_order(timeInForce=timeInForce, **params)

    def create_limit_sell(self, timeInForce=bc.TIME_IN_FORCE_GTC, **params):
        """Send in a new limit sell order

        :param symbol: required
        :type symbol: str
        :param quantity: required
        :type quantity: decimal
        :param price: required
        :type price: str
        :param timeInForce: default Good till cancelled
        :type timeInForce: str
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param stopPrice: Used with stop orders
        :type stopPrice: decimal
        :param icebergQty: Used with iceberg orders
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'side': bc.SIDE_SELL
        })
        return self.create_limit_order(timeInForce=timeInForce, **params)

    def create_market_order(self, **params):
        """Send in a new market order

        :param symbol: required
        :type symbol: str
        :param side: required
        :type side: str
        :param quantity: required
        :type quantity: decimal
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'type': bc.ORDER_TYPE_MARKET
        })
        return self.create_order(**params)

    def create_market_buy(self, **params):
        """Send in a new market buy order

        :param symbol: required
        :type symbol: str
        :param quantity: required
        :type quantity: decimal
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'side': bc.SIDE_BUY
        })
        return self.create_market_order(**params)

    def create_market_sell(self, **params):
        """Send in a new market sell order

        :param symbol: required
        :type symbol: str
        :param quantity: required
        :type quantity: decimal
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        See order endpoint for full response options

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, ConnectionError

        """
        params.update({
            'side': bc.SIDE_SELL
        })
        return self.create_market_order(**params)

    def create_test_order(self, **params):
        """Test new order creation and signature/recvWindow long. Creates and
        validates a new order but does not send it into the matching engine.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#test-new-order-trade

        :param symbol: required
        :type symbol: str
        :param side: required
        :type side: str
        :param type: required
        :type type: str
        :param timeInForce: required if limit order
        :type timeInForce: str
        :param quantity: required
        :type quantity: decimal
        :param price: required
        :type price: str
        :param newClientOrderId: A unique id for the order. Automatically
        generated if not sent.
        :type newClientOrderId: str
        :param icebergQty: Used with iceberg orders
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL;
        default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: The number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {}

        :raises: ResponseException, APIException, OrderException,
        OrderMinAmountException, OrderMinPriceException,
        OrderMinTotalException, OrderUnknownSymbolException,
        OrderInactiveSymbolException, NoAPISecretException, ConnectionError


        """
        return self._post('order/test', True, data=params)

    def query_order(self, retry=True, **params):
        """Check an order's status. Either orderId or origClientOrderId must be
        sent.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#query-order-user_data

        :param symbol: required
        :type symbol: str
        :param orderId: The unique order id
        :type orderId: int
        :param origClientOrderId: optional
        :type origClientOrderId: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "symbol": "LTCBTC",
                "orderId": 1,
                "clientOrderId": "myOrder1",
                "price": "0.1",
                "origQty": "1.0",
                "executedQty": "0.0",
                "status": "NEW",
                "timeInForce": "GTC",
                "type": "LIMIT",
                "side": "BUY",
                "stopPrice": "0.0",
                "icebergQty": "0.0",
                "time": 1499827319559
            }

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        return self._get('order', True, data=params, retry=retry)

    def all_orders(self, **params):
        """Get all account orders; active, canceled, or filled.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#all-orders-user_data

        :param symbol: required
        :type symbol: str
        :param orderId: The unique order id
        :type orderId: int
        :param limit: Default 500; max 500.
        :type limit: int
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "orderId": 1,
                    "clientOrderId": "myOrder1",
                    "price": "0.1",
                    "origQty": "1.0",
                    "executedQty": "0.0",
                    "status": "NEW",
                    "timeInForce": "GTC",
                    "type": "LIMIT",
                    "side": "BUY",
                    "stopPrice": "0.0",
                    "icebergQty": "0.0",
                    "time": 1499827319559
                }
            ]

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        return self._get('allOrders', True, data=params)

    @staticmethod
    def order_is_open(query_res):
        """Determines whether an order is open, given the result of a call to
        Client.query_order()."""
        return query_res['status'] in \
                {bc.ORDER_STATUS_NEW, bc.ORDER_STATUS_PARTIALLY_FILLED}

    def cancel_order_raw(self, retry=False, **params):
        return self._delete('order', True, data=params, retry=retry)
    def cancel_order(self, retry=True, check=True, **params):
        """Cancel an active order. Either orderId or origClientOrderId must be
        sent. Retries by default and succeeds if the order was already
        cancelled. If you don't want either of these behaviours, use
        cancel_order_raw() to access the REST endpoint directly.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#cancel-order-trade

        :param check: Enables checking. The function will not return
        until the order is cancelled. It will return the result of
        Client.query_order(), which it used to determine whether the order was
        actually cancelled.
        :type check: bool
        :param symbol: required
        :type symbol: str
        :param orderId: The unique order id
        :type orderId: int
        :param origClientOrderId: optional
        :type origClientOrderId: str
        :param newClientOrderId: Used to uniquely identify this cancel.
        Automatically generated by default.
        :type newClientOrderId: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        try:
            self.cancel_order_raw(retry=retry, **params)
        except APIException as e:
            if e.code != bc.E_CANCEL_REJECTED or \
                    e.message != bc.EMSG_UNKNOWN_ORDER:
                raise
        if check:
            while True:
                res = self.query_order(retry=retry, **params)
                if not self.order_is_open(res):
                    return res
                time.sleep(1)

    def open_orders(self, **params):
        """Get all open orders on a symbol.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#current-open-orders-user_data

        :param symbol: optional
        :type symbol: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            [
                {
                    "symbol": "LTCBTC",
                    "orderId": 1,
                    "clientOrderId": "myOrder1",
                    "price": "0.1",
                    "origQty": "1.0",
                    "executedQty": "0.0",
                    "status": "NEW",
                    "timeInForce": "GTC",
                    "type": "LIMIT",
                    "side": "BUY",
                    "stopPrice": "0.0",
                    "icebergQty": "0.0",
                    "time": 1499827319559
                }
            ]

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        return self._get('openOrders', True, data=params)

    # User Stream Endpoints
    def account(self, **params):
        """Get current account information.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#account-information-user_data

        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "makerCommission": 15,
                "takerCommission": 15,
                "buyerCommission": 0,
                "sellerCommission": 0,
                "canTrade": true,
                "canWithdraw": true,
                "canDeposit": true,
                "balances": [
                    {
                        "asset": "BTC",
                        "free": "4723846.89208129",
                        "locked": "0.00000000"
                    },
                    {
                        "asset": "LTC",
                        "free": "4763368.68006011",
                        "locked": "0.00000000"
                    }
                ]
            }

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        return self._get('account', True, data=params, retry=True)

    def asset_balances(self, **params):
        """Get a dictionary of all asset balances with the asset names as the
        keys. This is a convenient reformatting of the actual asset balances
        returned from Binance. Data source used:

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#account-information-user_data

        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: dictionary

        .. code-block:: python

            {
                'BTC': {
                        'free': '4723846.89208129',
                        'locked': '0.00000000'
                    }
                'ETH': {
                        'free': '4723846.89208129',
                        'locked': '0.00000000'
                    }
                ...
            }

        :raises: ResponseException, APIException, ConnectionError,
        ConnectionError

        """
        res = self.account(**params)
        bals = {}
        for bal in res['balances']:
            name = bal.pop('asset')
            bals[name] = bal
        return bals


    def asset_balance(self, asset, **params):
        """Get the balance of the asset "asset".

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#account-information-user_data

        :param asset: required
        :type asset: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: dictionary

        .. code-block:: python

            {
                "asset": "BTC",
                "free": "4723846.89208129",
                "locked": "0.00000000"
            }

        :raises: ResponseException, APIException, KeyError, ConnectionError

        """
        res = self.asset_balances(**params)
        return res[asset]

    def my_trades(self, **params):
        """Get trades for a specific symbol.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#account-trade-list-user_data

        :param symbol: required
        :type symbol: str
        :param limit: Default 500; max 500.
        :type limit: int
        :param fromId: TradeId to fetch from. Default gets most recent trades.
        :type fromId: int
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            [
                {
                    "id": 28457,
                    "price": "4.00000100",
                    "qty": "12.00000000",
                    "commission": "10.10000000",
                    "commissionAsset": "BNB",
                    "time": 1499865549590,
                    "isBuyer": true,
                    "isMaker": false,
                    "isBestMatch": true
                }
            ]

        :raises: ResponseException, APIException, NoAPISecretException,
        ConnectionError

        """
        return self._get('myTrades', True, data=params)

    def account_status(self, **params):
        """Get account status detail.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/wapi-api.md#account-status-user_data

        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "msg": "Order failed:Low Order fill rate! "
                        "Will be reactivated after 5 minutes.",
                "success": true,
                "objs": [
                    "5"
                ]
            }

        :raises: WithdrawException, ConnectionError

        """
        res = self._request_withdraw_api('get', 'accountStatus.html',
                True, data=params)
        if not res['success']:
            raise WithdrawException(res['msg'])
        return res

    # Withdraw Endpoints

    def withdraw(self, **params):
        """Submit a withdraw request.

        https://www.binance.com/restapipub.html

        Assumptions:

        - You must have Withdraw permissions enabled on your API key
        - You must have withdrawn to the address specified through the website
          and approved the transaction via email

        :param asset: required
        :type asset: str
        :type address: required
        :type address: str
        :type addressTag: optional - Secondary address identifier for coins
        like XRP,XMR etc.
        :type address: str
        :param amount: required
        :type amount: decimal
        :param name: optional - Description of the address, default asset value
        passed will be used
        :type name: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "msg": "success",
                "success": true,
                "id":"7213fea8e94b4a5593d507237e5a555b"
            }

        :raises: ResponseException, APIException, WithdrawException,
        ConnectionError

        """
        # force a name for the withdrawal if one not set
        if 'asset' in params and 'name' not in params:
            params['name'] = params['asset']
        res = self._request_withdraw_api('post', 'withdraw.html', True,
                data=params)
        if not res['success']:
            raise WithdrawException(res['msg'])
        return res

    def deposit_history(self, **params):
        """Fetch deposit history.

        https://www.binance.com/restapipub.html

        :param asset: optional
        :type asset: str
        :type status: 0(0:pending,1:success) optional
        :type status: int
        :param startTime: optional
        :type startTime: long
        :param endTime: optional
        :type endTime: long
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "depositList": [
                    {
                        "insertTime": 1508198532000,
                        "amount": 0.04670582,
                        "asset": "ETH",
                        "status": 1
                    }
                ],
                "success": true
            }

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._request_withdraw_api('get', 'depositHistory.html', True,
                data=params)

    def withdraw_history(self, **params):
        """Fetch withdraw history.

        https://www.binance.com/restapipub.html

        :param asset: optional
        :type asset: str
        :type status: 0(0:Email Sent,1:Cancelled 2:Awaiting Approval 3:Rejected
        4:Processing 5:Failure 6Completed) optional
        :type status: int
        :param startTime: optional
        :type startTime: long
        :param endTime: optional
        :type endTime: long
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "withdrawList": [
                    {
                        "amount": 1,
                        "address":
                            "0x6915f16f8791d0a1cc2bf47c13a6b2a92000504b",
                        "asset": "ETH",
                        "applyTime": 1508198532000
                        "status": 4
                    },
                    {
                        "amount": 0.005,
                        "address":
                            "0x6915f16f8791d0a1cc2bf47c13a6b2a92000504b",
                        "txId": "0x80aaabed54bdab3f6de5868f89929a23"
                                  "71ad21d666f20f7393d1a3389fad95a1",
                        "asset": "ETH",
                        "applyTime": 1508198532000,
                        "status": 4
                    }
                ],
                "success": true
            }

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._request_withdraw_api('get', 'withdrawHistory.html', True,
                data=params)

    def deposit_address(self, **params):
        """Fetch a deposit address for a symbol

        https://www.binance.com/restapipub.html

        :param asset: required
        :type asset: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response

        .. code-block:: python

            {
                "address": "0x6915f16f8791d0a1cc2bf47c13a6b2a92000504b",
                "success": true,
                "addressTag": "1231212",
                "asset": "BNB"
            }

        :raises: ResponseException, APIException, ConnectionError

        """
        return self._request_withdraw_api('get', 'depositAddress.html', True,
                data=params)

    # User Stream Endpoints

    def stream_listen_key(self):
        """Start a new user data stream and return the listen key
        If a stream already exists it should return the same key.
        If the stream becomes invalid a new key is returned.

        Can be used to keep the user stream alive.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#start-user-data-stream-user_stream

        :returns: API response

        .. code-block:: python

            {
                "listenKey": "pqia91ma19a5s61cv6a81va65sdf19v8"
                             "a65a1a5s61cv6a81va65sdf19v8a65a1"
            }

        :raises: ResponseException, APIException, NoAPIKeyException,
        ConnectionError

        """
        self._assert_api_key()
        res = self._post('userDataStream', False, data={})
        return res['listenKey']

    def stream_keepalive(self, listenKey):
        """PING a user data stream to prevent a time out.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#keepalive-user-data-stream-user_stream

        :param listenKey: required
        :type listenKey: str

        :returns: API response

        .. code-block:: python

            {}

        :raises: ResponseException, APIException, NoAPIKeyException,
        ConnectionError

        """
        self._assert_api_key()
        params = {
            'listenKey': listenKey
        }
        return self._put('userDataStream', False, data=params)

    def stream_close(self, listenKey):
        """Close out a user data stream.

        https://github.com/binance-exchange/binance-official-api-docs
        /blob/master/rest-api.md#close-user-data-stream-user_stream

        :param listenKey: required
        :type listenKey: str

        :returns: API response

        .. code-block:: python

            {}

        :raises: ResponseException, APIException, NoAPIKeyException,
        ConnectionError

        """
        self._assert_api_key()
        params = {
            'listenKey': listenKey
        }
        return self._delete('userDataStream', False, data=params)
