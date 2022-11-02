# README #

Freqtrade as of today does not support DYDX, this repo contains an implementation of a minimal API endpoint to connect with [Freqtrade](https://freqtrade.io) webhooks.

> :warning: **This is a WIP, not tested in production**
> 
### Setup ###

Populate a file called `private_config.py` with your data.

Change the values at the start of the `main.py` file to fit your needs.

Start the API by running :

```console
# python3 main.py 
``` 

A logging file will be created at the same dir called log.txt.

### Freqtrade config ###

First step is enable webhooks in your Freqtrade config.
We are only using status, entry and exit webhooks for now.

Freqtrade posts form encoded to our API.

```yaml
"webhook": {
    "enabled": true,
    "url": "http://127.0.0.1:7000/api",
    "webhookentry": {
        "command": "Entry",
        "pair": "{pair}",
        "trade_id": "{trade_id}",
        "direction": "{direction}",
        "amount": "{amount}",
        "stake_amount": "{stake_amount}",
        "open_rate": "{open_rate}",
    },
    "webhookexit": {
        "command": "Exit",
        "pair": "{pair}",
        "trade_id": "{trade_id}",
        "direction": "{direction}",
        "amount": "{amount}",
        "stake_amount": "{stake_amount}",
        "open_rate": "{open_rate}",
    },
    "webhookstatus": {
        "command": "Status",
        "status": "{status}",
    },
},

```

### Testing with CURL ###

Test the status command :
```console
curl -X POST http://127.0.0.1:7000/api -F command=Status
```

Test an entry order :
```console
curl -X POST http://127.0.0.1:7000/api -F command=Entry \
    -F pair="BTC/USDT" \
    -F trade_id=10 \
    -F direction=Long \
    -F amount=0.001 \
    -F stake_amount=10 \
    -F open_rate=100 
```
```console
curl -X POST http://127.0.0.1:7000/api -F command=Exit \
    -F pair="ETH/USDT" \
    -F trade_id=10 \
    -F direction=Long \
    -F amount=0.1 \
    -F stake_amount=20 \
    -F open_rate=120.111 
```


Note that data must be formatted as if it was sent by Freqtrade.
Change the values according to what you want to test.

### Security ###

lol

