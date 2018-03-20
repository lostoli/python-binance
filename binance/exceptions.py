import binance.constants as bc

class APIException(Exception):
    def __init__(self, response):
        self.status_code = 0
        code = None
        try:
            json_res = response.json()
            code = int(json_res['code'])
        except ValueError:
            self.message = 'Invalid JSON error message from Binance: ' \
                    '{}'.format(response.text)
        else:
            self.code = code
            self.message = json_res['msg']
        self.status_code = response.status_code
        self.response = response
        self.request = getattr(response, 'request', None)

    def __str__(self):  # pragma: no cover
        return 'APIError(code={}): {}'.format(self.code, self.message)


class ResponseException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return 'ResponseException: {}'.format(self.message)


class OrderException(Exception):

    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return 'OrderException(code={}): {}'.format(self.code, self.message)


class OrderMinAmountException(OrderException):

    def __init__(self, value):
        message = 'Amount must be a multiple of {}'.format(value)
        super().__init__(bc.E_INVALID_MESSAGE, message)


class OrderMinPriceException(OrderException):

    def __init__(self, value):
        message = 'Price must be at least {}'.format(value)
        super().__init__(bc.E_INVALID_MESSAGE, message)


class OrderMinTotalException(OrderException):

    def __init__(self, value):
        message = 'Total must be at least {}'.format(value)
        super().__init__(bc.E_INVALID_MESSAGE, message)


class OrderUnknownSymbolException(OrderException):

    def __init__(self, value):
        message = 'Unknown symbol {}'.format(value)
        super().__init__(bc.E_INVALID_MESSAGE, message)


class OrderInactiveSymbolException(OrderException):

    def __init__(self, value):
        message = 'Attempting to trade an inactive symbol {}'.format(value)
        super().__init__(bc.E_INVALID_MESSAGE, message)


class WithdrawException(Exception):
    def __init__(self, message):
        if message == u'参数异常':
            message = 'Withdraw to this address through the website first'
        self.message = message

    def __str__(self):
        return 'WithdrawException: {}'.format(self.message)


class NoAPIKeyException(Exception):
    def __str__(self):
        return 'NoAPIKeyException: This endpoint requires an API key.'


class NoAPISecretException(Exception):
    def __str__(self):
        return 'NoAPISecretException: This endpoint requires an API secret.'


class ConnectionError(Exception):
    def __str__(self):
        return 'ConnectionError: Communication with Binance was interrupted ' \
                'due to a network error.'
