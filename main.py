from flask import Flask, jsonify, request, send_file
from dydx3.constants import ORDER_SIDE_BUY, ORDER_TYPE_LIMIT, ORDER_SIDE_SELL
import decimal
import time
from dydx3 import Client

from private_config import \
    API_SECRET, API_KEY, API_PASSPHRASE, \
    STARK_PRIVATE_KEY, \
    ETHEREUM_ADDRESS, \
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import requests
import logging

app = Flask(__name__)

PORT = 7000

# Default API endpoint for DYDX Exchange
DYDX_HOST = 'https://api.dydx.exchange/'

# Stake currency, only USD is supported, do not change.
STAKE_CURRENCY = 'USD'
# FOK, GTT or IOK
TIME_IN_FORCE = 'GTT'
# Post only is used to make sure your order executes only as a maker
POST_ONLY = False

# Maximum Fee as a percentage
# Tier 1 in DYDX is 0.05%
LIMIT_FEE_PERCENT = '0.051'
# LIVE for active trading DRY for testing
MODE = 'DRY'
# Order expiration in seconds
ORDER_EXPIRATION = 86400
# If margin fraction requirements for the market are higher than that, do not take the trade.
INITIAL_MARGIN_FRACTION_LIMIT = '0.5'
# TELEGRAM config (needs token and chat_id on private config)
TELEGRAM_ENABLED = True
TELEGRAM_SEND_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'

# If True, the trade will go through only if the asset is included in the allowed asset list.
CHECK_ALLOWED_ASSET = False
ALLOWED_ASSETS = ['BTC', 'ETH']


# Post message to telegram
def send_telegram_message(message):
    if TELEGRAM_ENABLED:
        try:
            requests.post(TELEGRAM_SEND_URL, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message})
        except Exception as err:
            logging.error('Error sending telegram message. Exception : {}'.format(err))

# API endpoint listening on http://localhost:PORT/api
@app.route('/api', methods=['POST'])
def position():
    logging.info('>> API hit, data dump follows : {}'.format(request.form))
    command = request.form['command']
    logging.info('Command : {}'.format(command))
    if command in ['Entry', 'Exit']:
        try:
            pair = request.form['pair']
            trade_id = request.form['trade_id']
            direction = request.form['direction']
            if direction not in ['Long', 'Short']:
                logging.error('Direction must be either Long or Short, but it was : {}'.format(direction))
                return 'KO'
            amount = decimal.Decimal(request.form['amount'])
            open_rate = decimal.Decimal(request.form['open_rate'])
            if command == 'Exit':
                limit = decimal.Decimal(request.form['limit'])
            asset = pair.split("/")[0]
            if CHECK_ALLOWED_ASSET:
                if asset not in ALLOWED_ASSETS:
                    logging.error('The asset is not in the allowed assets list.')
                    return 'KO'
            market = asset + '-' + STAKE_CURRENCY
        except Exception as err:
            logging.error('Error getting parameters. Exception : {}'.format(err))
            return 'KO'

        # Get our position ID.
        client = create_client()
        account_response = client.private.get_account()
        account = account_response.data['account']
        position_id = account['positionId']

        order_params = {
            'position_id': position_id,
            'market': market,
            'order_type': ORDER_TYPE_LIMIT,
            'post_only': POST_ONLY,
            'price': str(open_rate) if command == 'Entry' else str(limit),
            'time_in_force': TIME_IN_FORCE,
            'expiration_epoch_seconds': int(time.time()) + ORDER_EXPIRATION,
        }
        logging.info('Order params before setting side: {}'.format(order_params))
        # Check command and direction to properly set order side
        if command == 'Entry':
            if market in account['openPositions']:
                logging.error('There is already an open position for {}, ignoring order.'.format(market))
                return 'KO'
            if direction == 'Short':
                order_params['side'] = ORDER_SIDE_SELL
            elif direction == 'Long':
                order_params['side'] = ORDER_SIDE_BUY
        elif command == 'Exit':
            if market not in account['openPositions']:
                logging.error('Trying to exit a position, but no open position found for {}, ignoring order.'.format(market))
                return 'KO'
            elif account['openPositions'][market]['side'].lower() != direction.lower():
                logging.error('Trying to exit a position on the wrong direction for {}, NGMI.'.format(market))
                return 'KO'
            if direction == 'Short':
                order_params['side'] = ORDER_SIDE_BUY
            elif direction == 'Long':
                order_params['side'] = ORDER_SIDE_SELL

        try:
            # Get market data for pair
            market_data = client.public.get_markets(market)
            # Check Initial Margin Fraction requirementes are met while entering a position
            if command == 'Entry' and decimal.Decimal(INITIAL_MARGIN_FRACTION_LIMIT) < decimal.Decimal(market_data.data['markets'][market]['initialMarginFraction']):
                logging.info('Initial margin fraction limit is higher than the current market limit ({}), '
                             'not taking the trade', market_data.data['markets'][market]['initialMarginFraction'])
                return 'KO'
            # Make sure order size is a multiple of stepSize for this market.
            step = decimal.Decimal(market_data.data['markets'][market]['stepSize'])
            newsize = step * round(decimal.Decimal(amount) / step)
            order_params['size'] = str(round(newsize, len(market_data.data['markets'][market]['assetResolution'])))
            order_params['limit_fee'] = str((amount * decimal.Decimal(LIMIT_FEE_PERCENT)) / decimal.Decimal('100'))
            # Make sure price is a multiple of tickSize for this market
            tick = decimal.Decimal(market_data.data['markets'][market]['tickSize'])
            newprice = tick * round(decimal.Decimal(order_params['price']) / tick)
            order_params['price'] = str(newprice)
            logging.info('[{} mode] Posting order with data :{}'.format(MODE, order_params))
            if MODE == 'LIVE':
                order_response = client.private.create_order(**order_params)
                order_id = order_response.data['order']['id']
                message = 'Order {} successfully posted, order response data : {}'.format(order_id, order_response.data['order'])
                logging.info(message)
                send_telegram_message(message)
        except Exception as err:
            message = 'Error posting order : {}'.format(err)
            logging.error(message)
            send_telegram_message(message)
            return 'KO'
    elif command == 'Status':
        logging.info('Status received : {}'.format(request.form['command']))
    elif command == 'Account':
        logging.info('Account request received.')
        client = create_client()
        account_response = client.private.get_account()
        logging.info('Account  data : {}'.format(account_response.data))
    else:
        logging.info('Unknown command (or no command) received. Ignoring.')
        return 'KO'
    return 'OK'


# Creates a DYDX API client
def create_client() -> Client:
    client = Client(
        host=DYDX_HOST,
        api_key_credentials={
            'key': API_KEY,
            'secret': API_SECRET,
            'passphrase': API_PASSPHRASE},
        stark_private_key=STARK_PRIVATE_KEY,
        default_ethereum_address=ETHEREUM_ADDRESS,
    )
    return client


if __name__ == '__main__':
    logging.basicConfig(
        filename='log.txt',
        encoding='utf-8',
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app.run(debug=False, port=PORT)
