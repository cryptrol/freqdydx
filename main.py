from flask import Flask, jsonify, request, send_file
from dydx3.constants import ORDER_SIDE_BUY, ORDER_TYPE_LIMIT, ORDER_SIDE_SELL, ORDER_TYPE_MARKET, ORDER_TYPE_STOP, ORDER_TYPE_TAKE_PROFIT
import time
from dydx3 import Client

import requests
import logging

app = Flask(__name__)

from private_config import \
    API_SECRET, API_KEY, API_PASSPHRASE, \
    STARK_PRIVATE_KEY, \
    ETHEREUM_ADDRESS, \
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

PORT = 5000

# Default API endpoint for DYDX Exchange
DYDX_HOST = 'https://api.dydx.exchange/'

# Stake currency, only USD is supported, do not change.
STAKE_CURRENCY = 'USD'

# Enable Stop Loss
ENABLE_SL = True
STOP_LOSS_PERC = 0.5 # Percent - Could be sent by freqtrade in the future for individual values per pair

# Enable Take Profit
ENABLE_TP = True
PROFIT_PERC = 0.5 # Percent - Could be sent by freqtrade in the future for individual values per pair

# Post only is used to make sure your order executes only as a maker
POST_ONLY = False

# Maximum Fee as a percentage
# Tier 1 in DYDX is 0.05%
LIMIT_FEE_PERCENT = 0.5

# LIVE for active trading DRY for testing
MODE = 'LIVE'

# Order expiration in seconds
ORDER_EXPIRATION = 86400

# If margin fraction requirements for the market are higher than that, do not take the trade.
INITIAL_MARGIN_FRACTION_LIMIT = 0.5

# TELEGRAM config (needs token and chat_id on private config)
TELEGRAM_ENABLED = False
TELEGRAM_SEND_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'

# If True, the trade will go through only if the asset is included in the allowed asset list.
CHECK_ALLOWED_ASSET = True
ALLOWED_ASSETS = ['ETH', 'SOL', 'MATIC', 'AVAX', 'DOGE', 'ETC', 'ATOM', 'ADA', 'LTC', 'XMR','BNB','XRP']


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
            amount = float(request.form['amount'])
            open_rate = float(request.form['open_rate'])
            if command == 'Exit':
                limit = float(request.form['limit'])
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
        market_req = client.public.get_markets(market=market)
        price_long = float(market_req.data['markets'][market]['oraclePrice']) # Oracle price for longs
        price_short = float(market_req.data['markets'][market]['indexPrice']) # Index price for shorts
        order_params = {
            'position_id': position_id,
            'market': market,
            'order_type': ORDER_TYPE_MARKET if command == 'Exit' else ORDER_TYPE_LIMIT,
            'post_only': POST_ONLY,
            'price': price_long if direction == 'Long' else price_short,
            'reduce_only': True if command == 'Exit' else False,
            'time_in_force': str('IOC'),
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
            if command == 'Entry' and INITIAL_MARGIN_FRACTION_LIMIT < float(market_data.data['markets'][market]['initialMarginFraction']):
                logging.info('Initial margin fraction limit is higher than the current market limit ({}), '
                             'not taking the trade', market_data.data['markets'][market]['initialMarginFraction'])
                return 'KO'
            # Make sure order size is a multiple of stepSize for this market.
            step = float(market_data.data['markets'][market]['stepSize'])
            newsize = step * round(float(amount) / step)
            order_params['size'] = str(round(newsize, len(market_data.data['markets'][market]['assetResolution'])))
            #order_params['limit_fee'] = str((amount * LIMIT_FEE_PERCENT) / 100)
            order_params['limit_fee'] = str(0.1)
            # Make sure price is a multiple of tickSize for this market
            tick = float(market_data.data['markets'][market]['tickSize'])
            newprice = round(tick * round(float(order_params['price']) / tick),3)
            order_params['price'] = str(newprice)
            logging.info('[{} mode] Posting order with data :{}'.format(MODE, order_params))
            if MODE == 'LIVE':
                client.private.cancel_all_orders(market=market)
                time.sleep(2)
                order_response = client.private.create_order(**order_params)
                order_id = order_response.data['order']['id']
                order_status = order_response.data['order']['status']
                order_price = float(order_response.data['order']['price'])
                #order_amount = order_response.data['order']['size']
                message = 'Order {} successfully posted, order response data : {}'.format(order_id, order_response.data['order'])
                logging.info(order_response)
                logging.info(message)
                send_telegram_message(message)
                time.sleep(2)
                if command == 'Entry':
                    ordersize = str(round(newsize, len(market_data.data['markets'][market]['assetResolution'])))
                    if ENABLE_SL:
                        if direction == 'Long':
                            stop_limit_price = '%.1f' % (order_price * (1 - (STOP_LOSS_PERC/100)))
                            stop_limit_trigger = '%.1f' % (order_price * (1 - (STOP_LOSS_PERC/100)))
                        else:
                            stop_limit_price = '%.1f' % (order_price * (1 + (STOP_LOSS_PERC/100)))
                            stop_limit_trigger = '%.1f' % (order_price * (1 + (STOP_LOSS_PERC/100)))
                            
                        stop_limit_price = round(tick * round(float(stop_limit_price) / tick),4)
                        stop_limit_trigger = round(tick * round(float(stop_limit_trigger) / tick),4)
                        
                        stoploss_order = client.private.create_order(
                            position_id=position_id,
                            market=market,
                            side=ORDER_SIDE_SELL if direction == 'Long' else ORDER_SIDE_BUY,
                            order_type=ORDER_TYPE_STOP,
                            post_only=False,
                            reduce_only=True,
                            size=ordersize,
                            price=str(stop_limit_price),
                            trigger_price=str(stop_limit_trigger),
                            limit_fee=str(0.1),
                            time_in_force= str('IOC'),
                            expiration_epoch_seconds=time.time() + 15000,
                        ).data
                        logging.info(stoploss_order)
                        
                    if ENABLE_TP:
                        if direction == 'Long':
                            take_profit_price = '%.1f' % (order_price * (1 + (PROFIT_PERC/100)))
                            trigger_profit_price = '%.1f' % (order_price * (1 + (PROFIT_PERC/100)))
                        else:
                            take_profit_price = '%.1f' % (order_price * (1 - (PROFIT_PERC/100)))
                            trigger_profit_price = '%.1f' % (order_price * (1 - (PROFIT_PERC/100)))
                        
                        take_profit_price = round(tick * round(float(take_profit_price) / tick),4)
                        trigger_profit_price = round(tick * round(float(trigger_profit_price) / tick),4)
                        
                        take_profit_order = client.private.create_order(
                            position_id=position_id,
                            market=market,
                            side=ORDER_SIDE_SELL if direction == 'Long' else ORDER_SIDE_BUY,
                            order_type=ORDER_TYPE_TAKE_PROFIT,
                            post_only=False,
                            size=ordersize,
                            reduce_only=True,
                            price=str(take_profit_price),
                            trigger_price=str(trigger_profit_price),
                            limit_fee=str(0.1),
                            time_in_force= str('IOC'),
                            expiration_epoch_seconds=time.time() + 15000,
                        ).data
                        logging.info(take_profit_order)
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
        filename='/app/log.txt',
        encoding='utf-8',
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app.run(debug=True, host='0.0.0.0', port=PORT)
