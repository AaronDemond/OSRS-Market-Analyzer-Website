from dataclasses import dataclass

import requests


WIKI_LATEST_PRICE_URL = 'https://prices.runescape.wiki/api/v1/osrs/latest'
WIKI_USER_AGENT = 'GE-Tools Live Feedback - demondsoftware@gmail.com'

STATUS_WATCHING = 'watching'
STATUS_UNDERCUT = 'undercut'
STATUS_OVERCUT = 'overcut'
STATUS_NO_PRICE = 'no_price'
STATUS_PAUSED = 'paused'


@dataclass(frozen=True)
class LiveFeedbackResult:
    status: str
    is_triggered: bool
    market_price: int | None
    market_time: int | None
    difference: int | None
    price_key: str | None
    message: str


def fetch_latest_prices(timeout=10):
    response = requests.get(
        WIKI_LATEST_PRICE_URL,
        headers={'User-Agent': WIKI_USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get('data') if isinstance(payload, dict) else None


def evaluate_live_feedback(side, target_price, price_data):
    try:
        target = int(target_price)
    except (TypeError, ValueError):
        target = 0

    if side == 'sell':
        market_price = _coerce_int((price_data or {}).get('low'))
        market_time = _coerce_int((price_data or {}).get('lowTime'))
        if market_price is None:
            return LiveFeedbackResult(
                status=STATUS_NO_PRICE,
                is_triggered=False,
                market_price=None,
                market_time=None,
                difference=None,
                price_key='low',
                message='No recent sell price is available.',
            )

        difference = target - market_price
        if market_price < target:
            return LiveFeedbackResult(
                status=STATUS_UNDERCUT,
                is_triggered=True,
                market_price=market_price,
                market_time=market_time,
                difference=difference,
                price_key='low',
                message=f'Someone is selling {difference:,} gp cheaper.',
            )

        return LiveFeedbackResult(
            status=STATUS_WATCHING,
            is_triggered=False,
            market_price=market_price,
            market_time=market_time,
            difference=market_price - target,
            price_key='low',
            message='Your sell price has not been undercut.',
        )

    if side == 'buy':
        market_price = _coerce_int((price_data or {}).get('high'))
        market_time = _coerce_int((price_data or {}).get('highTime'))
        if market_price is None:
            return LiveFeedbackResult(
                status=STATUS_NO_PRICE,
                is_triggered=False,
                market_price=None,
                market_time=None,
                difference=None,
                price_key='high',
                message='No recent buy price is available.',
            )

        difference = market_price - target
        if market_price > target:
            return LiveFeedbackResult(
                status=STATUS_OVERCUT,
                is_triggered=True,
                market_price=market_price,
                market_time=market_time,
                difference=difference,
                price_key='high',
                message=f'Someone is buying {difference:,} gp higher.',
            )

        return LiveFeedbackResult(
            status=STATUS_WATCHING,
            is_triggered=False,
            market_price=market_price,
            market_time=market_time,
            difference=target - market_price,
            price_key='high',
            message='Your buy price has not been overcut.',
        )

    return LiveFeedbackResult(
        status=STATUS_NO_PRICE,
        is_triggered=False,
        market_price=None,
        market_time=None,
        difference=None,
        price_key=None,
        message='Invalid watch side.',
    )


def evaluate_watch(watch, latest_prices):
    if not watch.is_active:
        return LiveFeedbackResult(
            status=STATUS_PAUSED,
            is_triggered=False,
            market_price=watch.last_market_price,
            market_time=watch.last_market_time,
            difference=None,
            price_key=None,
            message='This watch is paused.',
        )

    price_data = (latest_prices or {}).get(str(watch.item_id))
    return evaluate_live_feedback(watch.side, watch.target_price, price_data)


def _coerce_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
