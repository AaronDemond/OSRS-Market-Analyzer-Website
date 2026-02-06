

def clamp(x, lo, hi):
    return max(lo, min(x, hi))


def weighted_regression_slope(prices, volumes):
    n = len(prices)
    if n < 2:
        return 0.0

    x = list(range(n))
    total_weight = sum(volumes)

    if total_weight == 0:
        return 0.0

    x_mean = sum(x[i] * volumes[i] for i in range(n)) / total_weight
    y_mean = sum(prices[i] * volumes[i] for i in range(n)) / total_weight

    numerator = sum(
        volumes[i] * (x[i] - x_mean) * (prices[i] - y_mean)
        for i in range(n)
    )

    denominator = sum(
        volumes[i] * (x[i] - x_mean) ** 2
        for i in range(n)
    )

    return numerator / denominator if denominator else 0.0


def standard_deviation(values):
    if not values:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5



def compute_flip_confidence(api_data):
    """
    api_data: list of dicts from OSRS Wiki timeseries endpoint
    returns: flip confidence score (0–100)
    """

    # --- filter bad rows (null prices happen when there were no trades) ---
    cleaned = []
    for p in api_data:
        ah = p.get("avgHighPrice")
        al = p.get("avgLowPrice")
        hv = p.get("highPriceVolume")
        lv = p.get("lowPriceVolume")

        # require prices; volumes can safely default to 0 if missing
        if ah is None or al is None:
            continue

        cleaned.append({
            "avgHighPrice": ah,
            "avgLowPrice": al,
            "highPriceVolume": hv or 0,
            "lowPriceVolume": lv or 0,
        })

    if len(cleaned) < 3:
        return 0.0

    # --- extract series ---
    avg_high_prices = [p["avgHighPrice"] for p in cleaned]
    avg_low_prices  = [p["avgLowPrice"] for p in cleaned]
    high_volumes    = [p["highPriceVolume"] for p in cleaned]
    low_volumes     = [p["lowPriceVolume"] for p in cleaned]

    n = len(cleaned)

    # --- basic aggregates ---
    avg_price = (sum(avg_high_prices) + sum(avg_low_prices)) / (2 * n)
    avg_high  = sum(avg_high_prices) / n
    avg_low   = sum(avg_low_prices) / n

    total_high_volume = sum(high_volumes)
    total_low_volume  = sum(low_volumes)
    total_volume      = total_high_volume + total_low_volume

    # --- 1. Trend (volume-weighted regression) ---
    high_slope = weighted_regression_slope(avg_high_prices, high_volumes)
    low_slope  = weighted_regression_slope(avg_low_prices, low_volumes)

    weighted_slope = 0.6 * high_slope + 0.4 * low_slope

    trend_strength = clamp(weighted_slope / avg_price, -0.02, 0.02)
    trend_score = (trend_strength + 0.02) / 0.04

    # --- 2. Buy vs sell pressure ---
    buy_pressure = (total_high_volume / total_volume) if total_volume > 0 else 0.5
    pressure_score = clamp((buy_pressure - 0.5) * 2 + 0.5, 0.0, 1.0)

    # --- 3. Spread health ---
    spread_pct = (avg_high - avg_low) / avg_low if avg_low > 0 else 0.0
    spread_score = clamp(spread_pct / 0.03, 0.0, 1.0)

    # --- 4. Volume sufficiency ---
    volume_threshold = max(200, int(2000 * (avg_price / 1_000_000)))
    volume_score = clamp(total_volume / volume_threshold, 0.0, 1.0)

    # --- 5. Stability (noise penalty) ---
    mid_prices = [(avg_high_prices[i] + avg_low_prices[i]) / 2 for i in range(n)]
    price_std = standard_deviation(mid_prices)

    stability_score = 1.0 - clamp((price_std / avg_price) / 0.01, 0.0, 1.0)

    # --- final weighted score ---
    score = (
        0.35 * trend_score +
        0.25 * pressure_score +
        0.20 * spread_score +
        0.10 * volume_score +
        0.10 * stability_score
    )

    return round(score * 100, 1)




import requests

url = "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=1h&id=3024"

response = requests.get(
    url,
    headers={
        "User-Agent": "OSRS-Market-Analyzer"
    }
)

response.raise_for_status()  # raises error if request failed

api_data = response.json()["data"]

conf = compute_flip_confidence(api_data)
print(f"Flip Confidence Score: {conf}/100")
