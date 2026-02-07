"""
Comprehensive dump alert integration tests.

What:
    40 tests organized into 8 groups of 5.  Each group shares ONE database
    setup (same FiveMinTimeSeries rows, HourlyItemVolume rows, and all_prices
    dictionaries).  Within each group only the alert parameters change, producing
    different expected trigger outcomes.

Why:
    Proves that every dump-alert threshold independently gates triggering in
    realistic scenarios: discount_min, shock_sigma, sell_ratio_min, rel_vol_min,
    liquidity_floor, consistency_required, cooldown, confirmation_buckets, and
    the scope modes (single / multi / all-items).

How:
    1.  Each test creates a User + Alert with specific dump parameters.
    2.  The database is populated in a group helper (FiveMinTimeSeries,
        HourlyItemVolume) shared across the 5 tests.
    3.  Two calls to check_dump_alert simulate the mandatory initialization
        cycle (call 1 = set EWMA baseline, call 2 = detect shock).
    4.  Between calls we seed dump_state with a realistic pre-existing
        variance (var_idio) so that a sudden price drop yields a meaningful
        shock_sigma on call 2 — without this, the first valid shock is always
        -1.0 regardless of drop magnitude.
    5.  Terminal output shows: database items, alert params, expected vs actual.

EWMA Seeding Detail:
    On the very first shock computation, var_idio initialises to r_idio^2
    (because _update_ewma(None, x, alpha) = x).  This makes sigma = |r_idio|
    and shock_sigma = ±1.0 for ANY drop.  Real behaviour assumes many prior
    observations have built a "normal" variance baseline.  We simulate this
    by injecting var_idio = (0.005)^2 = 2.5e-5 (typical 0.5% 5-minute move
    variance) after call 1.
"""

import json
import math
import time
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, FiveMinTimeSeries, HourlyItemVolume


# =============================================================================
# ITEM CONSTANTS
# =============================================================================
# Each item has a unique numeric ID modelled after real OSRS items, and a
# human-readable name.  Groups reference items by these constants.

ITEM_A_ID = 4151       # Abyssal whip — liquid, mid-priced melee weapon
ITEM_B_ID = 11802      # Dragon crossbow — mid-tier ranged weapon
ITEM_C_ID = 13576      # Dragon warhammer — high-value, volatile
ITEM_D_ID = 11832      # Bandos chestplate — steady, well-traded armour
ITEM_E_ID = 12002      # Occult necklace — cheap, very liquid mage necklace

# ITEM_MAPPING: Maps item ID strings to display names, injected into
#               cmd.get_item_mapping to avoid live API calls in tests.
ITEM_MAPPING = {
    str(ITEM_A_ID): 'Abyssal whip',
    str(ITEM_B_ID): 'Dragon crossbow',
    str(ITEM_C_ID): 'Dragon warhammer',
    str(ITEM_D_ID): 'Bandos chestplate',
    str(ITEM_E_ID): 'Occult necklace',
}

# NORMAL_VAR_IDIO: Pre-seeded idiosyncratic return variance representing
#                  a "typical" 0.5% five-minute move.
# Why: Without pre-seeding, the first shock computation always yields
#      shock_sigma = ±1.0 because sigma = |r_idio|.  Setting var_idio to
#      (0.005)^2 makes a 10% drop yield shock_sigma ~ log(0.90)/0.005 ~ -21,
#      which easily exceeds thresholds like -4.0.
NORMAL_VAR_IDIO = 0.005 ** 2   # 2.5e-5


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# BACKGROUND_ITEM_IDS: Stable "market" items added to all_prices to make
#                      compute_market_drift() return ~0 when only a few test
#                      items are actually dumping.
# Why: If only dumping items exist in all_prices, the median return IS the
#      dump itself, so r_idio = 0 for every item and shock_sigma = 0.
#      Adding 20 stable items ensures the median return stays near 0,
#      simulating a realistic market where most items are stable.
BACKGROUND_ITEM_IDS = list(range(90001, 90021))  # 20 fake stable items


def _add_background_market(prices_dict, price=5000):
    """
    Add 20 stable background items to a prices dict.

    What: Injects fake stable items so compute_market_drift() returns ~0.
    Why: With only dumping items in all_prices, the market drift equals the
         dump return, making r_idio = 0 for all items.  Real markets have
         thousands of stable items; these 20 simulate that background.
    How: Adds 20 items at a fixed price, ensuring the median log return
         across all items is ~0 (since 20 stable items outnumber the
         few dumping items).

    Args:
        prices_dict: Mutable dict of item_id_str -> {high, low}.
        price: Fixed price for all background items (default 5000).

    Returns:
        dict: The same dict, modified in place and returned for convenience.
    """
    for bg_id in BACKGROUND_ITEM_IDS:
        prices_dict[str(bg_id)] = {'high': price, 'low': price}
    return prices_dict


def _make_command():
    """
    Create a fully initialised Command instance ready for check_dump_alert().

    What: Instantiates the management command and injects minimal test dependencies.
    Why: Tests call check_dump_alert() which needs stdout, price_history,
         sustained_state, dump_market_state, and get_item_mapping.
    How: Constructs a Command, wires StringIO for stdout, and stubs
         get_item_mapping to return ITEM_MAPPING.

    Returns:
        Command: Ready-to-use instance.
    """
    # cmd: The Command instance under test
    cmd = Command()
    # stdout: Captures any print output the command produces
    cmd.stdout = StringIO()
    # price_history: Required by other alert types; empty for dump tests
    cmd.price_history = defaultdict(list)
    # sustained_state: Required by sustained alert type; empty for dump tests
    cmd.sustained_state = {}
    # dump_market_state: Instance-level dict for computing market drift;
    #                    starts empty so we control initialization
    cmd.dump_market_state = {
        'last_mids': {},
        'market_drift': 0.0,
    }
    # get_item_mapping: Returns our test mapping instead of hitting the API
    cmd.get_item_mapping = lambda: ITEM_MAPPING
    return cmd


def _fresh_epoch():
    """
    Return a Unix-epoch string 5 minutes in the past (inside 130-min window).

    What: Produces a timestamp that passes the volume recency check.
    Why: HourlyItemVolume records must be within 130 minutes of now.
    How: timezone.now() - 5 min -> epoch string.

    Returns:
        str: Epoch seconds string.
    """
    return str(int((timezone.now() - timedelta(minutes=5)).timestamp()))


def _five_min_epoch(minutes_ago=2):
    """
    Return a Unix-epoch string for a FiveMinTimeSeries bucket.

    What: Produces a recent timestamp for 5-minute data.
    Why: FiveMinTimeSeries rows need timestamps for ordering.
    How: timezone.now() - minutes_ago -> epoch string.

    Args:
        minutes_ago: How many minutes in the past.

    Returns:
        str: Epoch seconds string.
    """
    return str(int((timezone.now() - timedelta(minutes=minutes_ago)).timestamp()))


def _create_hourly_volume(item_id, volume_gp, timestamp_str=None):
    """
    Insert a HourlyItemVolume record with the given volume in GP.

    What: Creates a fresh volume record for the liquidity gate.
    Why: Dump alerts require items to meet a minimum hourly GP volume.
    How: Calls HourlyItemVolume.objects.create with a fresh timestamp.

    Args:
        item_id: OSRS item ID.
        volume_gp: Hourly volume in gold pieces.
        timestamp_str: Optional epoch string; defaults to 5 minutes ago.

    Returns:
        HourlyItemVolume: The created record.
    """
    # ts: Timestamp for the volume record, defaulting to fresh (within recency window)
    ts = timestamp_str or _fresh_epoch()
    # item_name: Human-readable name for the DB record
    item_name = ITEM_MAPPING.get(str(item_id), f'Item {item_id}')
    return HourlyItemVolume.objects.create(
        item_id=item_id,
        item_name=item_name,
        volume=volume_gp,
        timestamp=ts,
    )


def _create_5m_bucket(item_id, avg_high, avg_low, high_vol, low_vol,
                       minutes_ago=2):
    """
    Insert a FiveMinTimeSeries record.

    What: Creates a single 5-minute trading bucket for an item.
    Why: Dump detection uses the latest 5m bucket for sell ratio, relative
         volume, avg_low_price (discount), and consistency checks.
    How: Calls FiveMinTimeSeries.objects.create with computed timestamp.

    Args:
        item_id: OSRS item ID.
        avg_high: Average high-side price in this bucket.
        avg_low: Average low-side price in this bucket.
        high_vol: Number of trades on the high (buy) side.
        low_vol: Number of trades on the low (sell) side.
        minutes_ago: How many minutes ago this bucket occurred.

    Returns:
        FiveMinTimeSeries: The created record.
    """
    # item_name: Human-readable name for display
    item_name = ITEM_MAPPING.get(str(item_id), f'Item {item_id}')
    return FiveMinTimeSeries.objects.create(
        item_id=item_id,
        item_name=item_name,
        avg_high_price=avg_high,
        avg_low_price=avg_low,
        high_price_volume=high_vol,
        low_price_volume=low_vol,
        timestamp=_five_min_epoch(minutes_ago),
    )


def _create_consistency_buckets(item_id, both_side_count, total=12):
    """
    Create FiveMinTimeSeries rows for the consistency check.

    What: Inserts `total` 5-minute buckets, `both_side_count` of which have
          volume on both high and low sides.
    Why: _check_dump_consistency requires at least 6 of 12 recent buckets to
         have both-side volume > 0.
    How: Creates `both_side_count` two-sided buckets and the remainder as
         one-sided (low_vol only).

    Args:
        item_id: OSRS item ID.
        both_side_count: Number of buckets with both high_vol > 0 and low_vol > 0.
        total: Total number of buckets to create (default 12).
    """
    # item_name: Human-readable name for display
    item_name = ITEM_MAPPING.get(str(item_id), f'Item {item_id}')
    for i in range(total):
        # offset: Minutes ago for this bucket; start at 7 to avoid collision
        #         with the "latest" bucket created separately at minutes_ago=2
        offset = 7 + i * 5
        if i < both_side_count:
            # Two-sided bucket: both high and low volume present
            FiveMinTimeSeries.objects.create(
                item_id=item_id, item_name=item_name,
                avg_high_price=1000, avg_low_price=950,
                high_price_volume=50, low_price_volume=50,
                timestamp=_five_min_epoch(offset),
            )
        else:
            # One-sided bucket: only low volume (sell side)
            FiveMinTimeSeries.objects.create(
                item_id=item_id, item_name=item_name,
                avg_high_price=1000, avg_low_price=950,
                high_price_volume=0, low_price_volume=50,
                timestamp=_five_min_epoch(offset),
            )


def _seed_var_idio(alert, item_id_str, var_idio=NORMAL_VAR_IDIO):
    """
    Inject a pre-existing var_idio into an alert's dump_state for one item.

    What: Patches the persisted EWMA variance so the next shock computation
          uses a realistic baseline instead of initialising to r_idio^2.
    Why: Without seeding, shock_sigma = ±1.0 on the first valid computation
         regardless of drop magnitude, because sigma = |r_idio|.
    How: Loads dump_state JSON, sets var_idio for the given item, saves back.

    Args:
        alert: Alert model instance (must already have dump_state from call 1).
        item_id_str: String item ID whose variance to seed.
        var_idio: Variance value to inject (default: NORMAL_VAR_IDIO = 2.5e-5).
    """
    # state: The full per-item state dict deserialized from the alert
    state = json.loads(alert.dump_state) if alert.dump_state else {}
    if item_id_str not in state:
        state[item_id_str] = {}
    state[item_id_str]['var_idio'] = var_idio
    alert.dump_state = json.dumps(state)
    alert.save(update_fields=['dump_state'])


def _run_dump_check(cmd, alert, all_prices):
    """
    Execute one cycle of the dump alert check and return the result.

    What: Calls compute_market_drift then check_dump_alert.
    Why: Market drift must be computed before each dump evaluation cycle.
    How: Refreshes the alert from DB, computes drift, evaluates.

    Args:
        cmd: Command instance.
        alert: Alert model instance.
        all_prices: Dict of item_id_str -> {high, low}.

    Returns:
        Result from check_dump_alert (list of dicts, True, or False).
    """
    # Refresh alert from DB to pick up any dump_state changes
    alert.refresh_from_db()
    # Compute market drift from current prices (updates cmd.dump_market_state)
    cmd.compute_market_drift(all_prices)
    return cmd.check_dump_alert(alert, all_prices)


def _triggered_item_ids(result):
    """
    Extract the set of triggered item ID strings from a check result.

    What: Normalises the various return types into a set of item ID strings.
    Why: check_dump_alert returns a list of dicts, True, or False depending
         on alert scope.  Tests need a uniform way to check which items fired.
    How: If result is a list, extracts 'item_id' from each dict.
         If True (single-item mode), returns {'single'} as a sentinel.
         If False/None, returns empty set.

    Args:
        result: Return value from check_dump_alert.

    Returns:
        set: Set of triggered item ID strings.
    """
    if isinstance(result, list):
        return {item['item_id'] for item in result}
    if result is True:
        return {'single'}
    return set()


def _print_test_header(group_name, test_name, db_items, alert_params,
                        expected_items):
    """
    Print formatted test information to the terminal.

    What: Displays the test context for debugging and human readability.
    Why: User requirement — each test must print its setup, params, and
         expected outcome.
    How: Simple print() calls with formatted strings.

    Args:
        group_name: Name of the test group.
        test_name: Name of the individual test.
        db_items: Dict of item_id -> short description.
        alert_params: Dict of alert configuration values.
        expected_items: List of expected triggered item names, or ['None'].
    """
    print(f"\n{'='*70}")
    print(f"GROUP: {group_name}")
    print(f"TEST:  {test_name}")
    print(f"{'='*70}")
    print("DATABASE ITEMS:")
    for item_id, desc in db_items.items():
        print(f"  {ITEM_MAPPING.get(str(item_id), item_id)}: {desc}")
    print("ALERT PARAMETERS:")
    for key, val in alert_params.items():
        print(f"  {key}: {val}")
    print(f"EXPECTED TO TRIGGER: {', '.join(expected_items) if expected_items else 'None'}")


def _print_result(expected_ids, actual_ids):
    """
    Print the expected vs actual outcome and a PASS/FAIL indicator.

    What: Shows whether the test matched expectations.
    Why: Makes terminal output immediately scannable.
    How: Compares two sets of item ID strings.

    Args:
        expected_ids: Set of expected triggered item ID strings.
        actual_ids: Set of actually triggered item ID strings.
    """
    # expected_names / actual_names: Human-readable item names for display
    expected_names = sorted(ITEM_MAPPING.get(i, i) for i in expected_ids)
    actual_names = sorted(ITEM_MAPPING.get(i, i) for i in actual_ids)
    status = "PASS" if expected_ids == actual_ids else "FAIL"
    print(f"ACTUAL TRIGGERED:   {', '.join(actual_names) if actual_names else 'None'}")
    print(f"STATUS: {status}")
    print(f"{'='*70}")


# =============================================================================
# MAIN TEST CLASS — all 40 tests in a single TestCase
# =============================================================================

class DumpAlertIntegrationTests(TestCase):
    """
    Integration tests for the dump alert engine.

    What: 8 groups × 5 tests = 40 tests validating the full check_dump_alert
          pipeline against real database records.
    Why: Proves each threshold parameter independently gates triggering, and
         that scope modes (single/multi/all) work correctly.
    How: Each group populates the DB with items at various states, then runs
         5 tests that differ only in alert parameters.  Tests assert which
         items trigger.
    """

    def setUp(self):
        """
        Create the test user shared by all tests.

        What: Creates a Django User instance for foreign key on Alert.
        Why: Alert model requires a user field.
        How: Uses Django's create_user helper.
        """
        # user: The owner of all test alerts
        self.user = User.objects.create_user(
            username='dump_test_user', password='testpass'
        )

    # =========================================================================
    # SHARED DB SETUP HELPERS — one per group
    # =========================================================================

    def _setup_group1_moderate_dump(self):
        """
        Group 1: Moderate Dump Scenario.

        What: Creates 4 items with varying levels of dump severity.
        Why: Tests that discount_min and shock_sigma thresholds correctly
             filter items at different dump magnitudes.
        How:
            Item A — Clear dump:   10% price drop, 85% sell ratio, high volume
            Item B — Moderate dump: 5% price drop, 75% sell ratio, high volume
            Item C — Borderline:    3% price drop, 72% sell ratio, moderate volume
            Item D — Stable:        0% price drop, 50% sell ratio, normal volume

        Database records created:
            - HourlyItemVolume: All items at 100M GP (well above default floor)
            - FiveMinTimeSeries: 12 consistent buckets each, plus one "latest"
              bucket with the dump characteristics

        Price scheme (call 1 -> call 2):
            Call 1 (normal):  all items at high=1000, low=1000 (mid=1000)
            Call 2 (dumped):
                A: high=900, low=900   (mid=900, -10%)
                B: high=950, low=950   (mid=950, -5%)
                C: high=970, low=970   (mid=970, -3%)
                D: high=1000, low=1000 (mid=1000, stable)
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]
        for item_id in items:
            # Create fresh hourly volume (100M GP) for liquidity gate
            _create_hourly_volume(item_id, 100_000_000)
            # Create 12 consistency buckets (all two-sided)
            _create_consistency_buckets(item_id, both_side_count=12)

        # Latest 5m buckets with dump characteristics
        # Item A: Clear dump — 85% sell ratio, 200 total volume, avg_low well below fair
        _create_5m_bucket(ITEM_A_ID, avg_high=950, avg_low=880,
                          high_vol=30, low_vol=170, minutes_ago=1)
        # Item B: Moderate — 75% sell, 150 total volume, avg_low moderately below fair
        _create_5m_bucket(ITEM_B_ID, avg_high=975, avg_low=930,
                          high_vol=38, low_vol=112, minutes_ago=1)
        # Item C: Borderline — 72% sell, 100 total volume, avg_low slightly below fair
        _create_5m_bucket(ITEM_C_ID, avg_high=985, avg_low=960,
                          high_vol=28, low_vol=72, minutes_ago=1)
        # Item D: Stable — 50% sell, 80 total volume, avg_low at fair
        _create_5m_bucket(ITEM_D_ID, avg_high=1000, avg_low=995,
                          high_vol=40, low_vol=40, minutes_ago=1)

        # all_prices for call 1 (normal prices — establishes EWMA baseline)
        # all items at mid=1000 so any drop on call 2 is measurable
        normal_prices = {}
        for item_id in items:
            normal_prices[str(item_id)] = {'high': 1000, 'low': 1000}
        # Add background stable items so market drift ~ 0
        _add_background_market(normal_prices)

        # all_prices for call 2 (dumped prices)
        dumped_prices = {
            str(ITEM_A_ID): {'high': 900, 'low': 900},     # -10%
            str(ITEM_B_ID): {'high': 950, 'low': 950},     # -5%
            str(ITEM_C_ID): {'high': 970, 'low': 970},     # -3%
            str(ITEM_D_ID): {'high': 1000, 'low': 1000},   # 0%
        }
        # Background items stay at same price -> drift ~ 0
        _add_background_market(dumped_prices)

        # db_items: Description dict for terminal printing
        db_items = {
            ITEM_A_ID: 'Clear dump: -10%, 85% sell, high vol',
            ITEM_B_ID: 'Moderate: -5%, 75% sell, high vol',
            ITEM_C_ID: 'Borderline: -3%, 72% sell, moderate vol',
            ITEM_D_ID: 'Stable: 0% drop, 50% sell, normal vol',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group2_volume_levels(self):
        """
        Group 2: High Volume Spike vs Low Volume.

        What: Creates 4 items with identical price drops but varying volume.
        Why: Tests that rel_vol_min and liquidity_floor correctly filter items.
        How:
            All items drop 10%, 85% sell ratio.
            Item A — 500 total bucket vol (huge spike over EWMA of ~50)
            Item B — 100 total bucket vol (moderate spike)
            Item C — 30 total bucket vol (barely above normal)
            Item D — 10 total bucket vol (below normal)

            HourlyItemVolume varies to test liquidity_floor:
            A: 500M GP, B: 100M GP, C: 10M GP, D: 1M GP
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]

        # Varied hourly volumes for liquidity gate testing
        hourly_volumes = {
            ITEM_A_ID: 500_000_000,
            ITEM_B_ID: 100_000_000,
            ITEM_C_ID: 10_000_000,
            ITEM_D_ID: 1_000_000,
        }
        # Varied bucket volumes for rel_vol testing
        bucket_volumes = {
            ITEM_A_ID: (75, 425),    # 500 total, 85% sell
            ITEM_B_ID: (15, 85),     # 100 total, 85% sell
            ITEM_C_ID: (5, 25),      # 30 total, 83% sell
            ITEM_D_ID: (2, 8),       # 10 total, 80% sell
        }

        for item_id in items:
            _create_hourly_volume(item_id, hourly_volumes[item_id])
            _create_consistency_buckets(item_id, both_side_count=12)
            high_v, low_v = bucket_volumes[item_id]
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=high_v, low_vol=low_v, minutes_ago=1)

        # All items at 1000 normally, drop to 900 (-10%)
        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        _add_background_market(normal_prices)
        dumped_prices = {str(i): {'high': 900, 'low': 900} for i in items}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: '500M GP/hr, 500 bucket vol (huge spike)',
            ITEM_B_ID: '100M GP/hr, 100 bucket vol (moderate spike)',
            ITEM_C_ID: '10M GP/hr, 30 bucket vol (small spike)',
            ITEM_D_ID: '1M GP/hr, 10 bucket vol (below normal)',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group3_sell_pressure(self):
        """
        Group 3: Sell Pressure Gradient.

        What: Creates 4 items with same price drop but sell ratios from 50% to 95%.
        Why: Tests that sell_ratio_min correctly filters at different thresholds.
        How:
            All items drop 10%, high bucket volume, high liquidity.
            Item A — 95% sell ratio (extreme dump pressure)
            Item B — 80% sell ratio (strong dump)
            Item C — 65% sell ratio (mild sell bias)
            Item D — 50% sell ratio (balanced trading)
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]

        # sell_configs: (high_vol, low_vol) tuples giving different sell ratios
        sell_configs = {
            ITEM_A_ID: (10, 190),    # 200 total, 95% sell
            ITEM_B_ID: (40, 160),    # 200 total, 80% sell
            ITEM_C_ID: (70, 130),    # 200 total, 65% sell
            ITEM_D_ID: (100, 100),   # 200 total, 50% sell
        }

        for item_id in items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id, both_side_count=12)
            high_v, low_v = sell_configs[item_id]
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=high_v, low_vol=low_v, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        _add_background_market(normal_prices)
        dumped_prices = {str(i): {'high': 900, 'low': 900} for i in items}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: '95% sell ratio (extreme)',
            ITEM_B_ID: '80% sell ratio (strong)',
            ITEM_C_ID: '65% sell ratio (mild)',
            ITEM_D_ID: '50% sell ratio (balanced)',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group4_market_selloff(self):
        """
        Group 4: Market-Wide Sell-Off vs Idiosyncratic Dump.

        What: Creates 4 items all dropping, but with different magnitudes.
              Market drift is large negative because most items drop.
        Why: Tests that shock_sigma correctly strips out market drift.
        How:
            Market context: 3 items drop 5%, 1 item drops 20%.
            Market drift ~ log(0.95) ~ -0.051 (median of the three -5% items).
            Item A — drops 20%: r_idio = log(0.80) - (-0.051) ~ -0.172 (big idio shock)
            Item B — drops 5%:  r_idio = log(0.95) - (-0.051) ~ 0.0 (follows market)
            Item C — drops 5%:  same as B
            Item D — drops 5%:  same as B

            Only Item A should trigger because it dropped far MORE than the market.
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]

        for item_id in items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id, both_side_count=12)
            # All items get a dump-like bucket (high sell ratio, high vol)
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=30, low_vol=170, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        # NOTE: Group 4 intentionally does NOT add background items because
        # the test is about market drift.  Tests that need to control drift
        # manually will handle it in the test method itself.
        dumped_prices = {
            str(ITEM_A_ID): {'high': 800, 'low': 800},   # -20%
            str(ITEM_B_ID): {'high': 950, 'low': 950},   # -5%
            str(ITEM_C_ID): {'high': 950, 'low': 950},   # -5%
            str(ITEM_D_ID): {'high': 950, 'low': 950},   # -5%
        }

        db_items = {
            ITEM_A_ID: 'Drops 20% (far more than market)',
            ITEM_B_ID: 'Drops 5% (follows market)',
            ITEM_C_ID: 'Drops 5% (follows market)',
            ITEM_D_ID: 'Drops 5% (follows market)',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group5_consistency(self):
        """
        Group 5: Consistency Check Scenarios.

        What: Creates 4 items with varying numbers of two-sided buckets.
        Why: Tests that consistency_required flag and the 6-of-12 rule work.
        How:
            All items dump 10%, 85% sell ratio, high volume.
            Item A — 12/12 two-sided buckets (fully consistent)
            Item B — 7/12 two-sided buckets (just above threshold)
            Item C — 5/12 two-sided buckets (just below threshold)
            Item D — 2/12 two-sided buckets (clearly inconsistent)
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]

        # consistency_counts: How many of 12 history buckets have both-side volume.
        # NOTE: The "latest" 5m bucket (created below at minutes_ago=1) also has
        # both-side volume and counts toward the 12-bucket query.  So the EFFECTIVE
        # both-side count is consistency_count + 1.  We set counts accordingly:
        #   A: 11 + 1 = 12/12 (fully consistent)
        #   B: 6 + 1 = 7/12  (just above 6-of-12 threshold)
        #   C: 4 + 1 = 5/12  (just below threshold)
        #   D: 1 + 1 = 2/12  (clearly inconsistent)
        consistency_counts = {
            ITEM_A_ID: 11,
            ITEM_B_ID: 6,
            ITEM_C_ID: 4,
            ITEM_D_ID: 1,
        }

        for item_id in items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id,
                                        both_side_count=consistency_counts[item_id])
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=30, low_vol=170, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        _add_background_market(normal_prices)
        dumped_prices = {str(i): {'high': 900, 'low': 900} for i in items}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: '12/12 two-sided buckets (fully consistent)',
            ITEM_B_ID: '7/12 two-sided buckets (above threshold)',
            ITEM_C_ID: '5/12 two-sided buckets (below threshold)',
            ITEM_D_ID: '2/12 two-sided buckets (clearly inconsistent)',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group6_cooldown_confirmation(self):
        """
        Group 6: Cooldown & Confirmation.

        What: Creates 2 clearly-dumping items.
        Why: Tests confirmation_buckets and cooldown behavior.
        How:
            Item A — drops 10%, 85% sell, high vol, fully consistent
            Item B — drops 10%, 85% sell, high vol, fully consistent
            Both should trigger under loose params; confirmation/cooldown block them.
        """
        items = [ITEM_A_ID, ITEM_B_ID]

        for item_id in items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id, both_side_count=12)
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=30, low_vol=170, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        _add_background_market(normal_prices)
        dumped_prices = {str(i): {'high': 900, 'low': 900} for i in items}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: 'Clear dump: -10%, 85% sell, consistent',
            ITEM_B_ID: 'Clear dump: -10%, 85% sell, consistent',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group7_discount_gradient(self):
        """
        Group 7: Extreme vs Marginal Discounts.

        What: Creates 4 items with discount percentages of ~1%, ~3%, ~5%, ~15%.
        Why: Tests that discount_min filters items at various thresholds.
        How:
            All items show price drops to trigger shock, high sell ratio,
            high volume.  The avg_low_price in the 5m bucket controls the
            discount from fair value.

            Fair value ~ 1000 (from call 1 EWMA init).
            Item A — avg_low=850 -> discount ~ 15%
            Item B — avg_low=950 -> discount ~ 5%
            Item C — avg_low=970 -> discount ~ 3%
            Item D — avg_low=990 -> discount ~ 1%
        """
        items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]

        # avg_lows: Controls the discount percentage from fair value (~1000)
        avg_lows = {
            ITEM_A_ID: 850,    # ~15% discount
            ITEM_B_ID: 950,    # ~5% discount
            ITEM_C_ID: 970,    # ~3% discount
            ITEM_D_ID: 990,    # ~1% discount
        }

        for item_id in items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id, both_side_count=12)
            _create_5m_bucket(item_id, avg_high=950,
                              avg_low=avg_lows[item_id],
                              high_vol=30, low_vol=170, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in items}
        _add_background_market(normal_prices)
        dumped_prices = {str(i): {'high': 900, 'low': 900} for i in items}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: f'avg_low=850, discount ~ 15%',
            ITEM_B_ID: f'avg_low=950, discount ~ 5%',
            ITEM_C_ID: f'avg_low=970, discount ~ 3%',
            ITEM_D_ID: f'avg_low=990, discount ~ 1%',
        }
        return normal_prices, dumped_prices, db_items, items

    def _setup_group8_scope_modes(self):
        """
        Group 8: All-Items Mode vs Specific Items.

        What: Creates 5 items, 3 dumping and 2 stable.
        Why: Tests is_all_items, item_ids (multi), and single item_id scoping.
        How:
            Item A, B, C — dump 10%, 85% sell, high vol, consistent
            Item D, E — stable, 50% sell, normal vol
        """
        dumping_items = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID]
        stable_items = [ITEM_D_ID, ITEM_E_ID]
        all_items = dumping_items + stable_items

        for item_id in all_items:
            _create_hourly_volume(item_id, 200_000_000)
            _create_consistency_buckets(item_id, both_side_count=12)

        # Dumping items: high sell ratio, high volume
        for item_id in dumping_items:
            _create_5m_bucket(item_id, avg_high=950, avg_low=880,
                              high_vol=30, low_vol=170, minutes_ago=1)

        # Stable items: balanced trading
        for item_id in stable_items:
            _create_5m_bucket(item_id, avg_high=1000, avg_low=995,
                              high_vol=50, low_vol=50, minutes_ago=1)

        normal_prices = {str(i): {'high': 1000, 'low': 1000} for i in all_items}
        _add_background_market(normal_prices)
        dumped_prices = {}
        for item_id in dumping_items:
            dumped_prices[str(item_id)] = {'high': 900, 'low': 900}
        for item_id in stable_items:
            dumped_prices[str(item_id)] = {'high': 1000, 'low': 1000}
        _add_background_market(dumped_prices)

        db_items = {
            ITEM_A_ID: 'Dumping -10%, 85% sell',
            ITEM_B_ID: 'Dumping -10%, 85% sell',
            ITEM_C_ID: 'Dumping -10%, 85% sell',
            ITEM_D_ID: 'Stable, 50% sell',
            ITEM_E_ID: 'Stable, 50% sell',
        }
        return normal_prices, dumped_prices, db_items, all_items

    # =========================================================================
    # SHARED RUN HELPER — runs call 1 (init), seeds var_idio, runs call 2
    # =========================================================================

    def _run_two_cycle_check(self, alert, normal_prices, dumped_prices,
                              items_to_seed):
        """
        Execute the standard two-cycle dump detection pattern.

        What: Runs call 1 with normal prices (EWMA init), seeds var_idio, then
              runs call 2 with dumped prices (detection).
        Why: Dump detection requires at least 2 calls — call 1 cannot trigger.
             var_idio must be pre-seeded for meaningful shock_sigma values.
        How:
            1. Create Command instance
            2. Call 1 with normal_prices (initialises EWMA state)
            3. Seed var_idio for each item (simulates historical variance)
            4. Call 2 with dumped_prices (computes shock and evaluates)

        Args:
            alert: Alert model instance with dump parameters set.
            normal_prices: Prices for call 1 (baseline).
            dumped_prices: Prices for call 2 (detection).
            items_to_seed: List of item IDs whose var_idio should be seeded.

        Returns:
            tuple: (result, triggered_ids) from call 2.
        """
        # cmd: Fresh Command instance for this test
        cmd = _make_command()

        # --- Call 1: Initialise EWMA state ---
        # This call sets last_mid, fair, expected_vol for each item.
        # It CANNOT trigger because last_mid is None on first observation.
        _run_dump_check(cmd, alert, normal_prices)

        # --- Seed var_idio with realistic historical variance ---
        # Without this, shock_sigma = ±1.0 on the first valid computation
        for item_id in items_to_seed:
            _seed_var_idio(alert, str(item_id))

        # --- Call 2: Detect dump with crashed prices ---
        result = _run_dump_check(cmd, alert, dumped_prices)
        # triggered: Set of item ID strings that actually triggered
        triggered = _triggered_item_ids(result)
        return result, triggered

    def _create_alert(self, **kwargs):
        """
        Create an Alert with dump type and merge default params with overrides.

        What: Factory for dump alerts with sensible defaults.
        Why: Each test only needs to specify the parameters it cares about;
             everything else gets defaults that maximise triggering (loose).
        How: Merges caller kwargs over base defaults, creates Alert.

        Default dump params (maximally loose):
            dump_discount_min=0.5      (very low discount bar)
            dump_shock_sigma=-0.5      (very loose shock bar)
            dump_sell_ratio_min=0.40   (low sell ratio bar)
            dump_rel_vol_min=0.1       (low relative volume bar)
            dump_liquidity_floor=100   (very low GP floor)
            dump_cooldown=0            (no cooldown)
            dump_confirmation_buckets=1 (trigger on first pass)
            dump_consistency_required=False (skip consistency)
            dump_fair_halflife=120
            dump_vol_halflife=360
            dump_var_halflife=120

        Args:
            **kwargs: Override any Alert field.

        Returns:
            Alert: The created alert instance.
        """
        # defaults: Maximally loose dump parameters so tests can tighten
        #           individual thresholds to test their gating effect
        defaults = {
            'user': self.user,
            'alert_name': 'Test Dump Alert',
            'type': 'dump',
            'is_active': True,
            'is_triggered': False,
            'dump_discount_min': 0.5,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 100,
            'dump_cooldown': 0,
            'dump_confirmation_buckets': 1,
            'dump_consistency_required': False,
            'dump_fair_halflife': 120,
            'dump_vol_halflife': 360,
            'dump_var_halflife': 120,
        }
        defaults.update(kwargs)
        return Alert.objects.create(**defaults)

    # =========================================================================
    # GROUP 1: MODERATE DUMP SCENARIO
    # Tests: discount_min and shock_sigma thresholds filter different items
    # =========================================================================

    def test_g1_01_loose_thresholds_all_dumpers_trigger(self):
        """All 3 dumping items trigger when thresholds are maximally loose."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group1_moderate_dump()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID,
                                     ITEM_C_ID, ITEM_D_ID]),
            'dump_discount_min': 0.5,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
        }
        _print_test_header(
            'Group 1: Moderate Dump', 'Loose thresholds -> A, B, C trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        # expected: A, B, C trigger (all dumping); D is stable (no price drop)
        expected = {str(ITEM_A_ID), str(ITEM_B_ID), str(ITEM_C_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g1_02_tighten_discount_to_4pct(self):
        """Raising discount_min to 4% filters out Item C (3% discount)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group1_moderate_dump()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID,
                                     ITEM_C_ID, ITEM_D_ID]),
            'dump_discount_min': 4.0,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
        }
        _print_test_header(
            'Group 1: Moderate Dump', 'discount_min=4% -> A, B trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        # expected: A and B have discount > 4%, C has ~3%, D is stable
        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g1_03_tighten_discount_to_8pct(self):
        """Raising discount_min to 8% leaves only Item A (12% discount)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group1_moderate_dump()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID,
                                     ITEM_C_ID, ITEM_D_ID]),
            'dump_discount_min': 8.0,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
        }
        _print_test_header(
            'Group 1: Moderate Dump', 'discount_min=8% -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g1_04_tighten_discount_to_20pct(self):
        """Setting discount_min to 20% means nothing triggers."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group1_moderate_dump()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID,
                                     ITEM_C_ID, ITEM_D_ID]),
            'dump_discount_min': 20.0,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
        }
        _print_test_header(
            'Group 1: Moderate Dump', 'discount_min=20% -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g1_05_tighten_sell_ratio(self):
        """Raising sell_ratio_min to 0.80 filters out B (75%) and C (72%)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group1_moderate_dump()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID,
                                     ITEM_C_ID, ITEM_D_ID]),
            'dump_discount_min': 0.5,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.80,
            'dump_rel_vol_min': 0.1,
        }
        _print_test_header(
            'Group 1: Moderate Dump', 'sell_ratio_min=0.80 -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        # A has 85% sell ratio, B has 75%, C has 72%, D has 50%
        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 2: HIGH VOLUME SPIKE VS LOW VOLUME
    # Tests: rel_vol_min and liquidity_floor thresholds
    # =========================================================================

    def test_g2_01_loose_vol_all_trigger(self):
        """Very loose volume requirements -> all 4 dumping items trigger."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group2_volume_levels()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 100,
        }
        _print_test_header(
            'Group 2: Volume Levels', 'Very loose vol -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g2_02_raise_liquidity_floor_50m(self):
        """Raising liquidity_floor to 50M filters out C (10M) and D (1M)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group2_volume_levels()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 50_000_000,
        }
        _print_test_header(
            'Group 2: Volume Levels', 'liquidity_floor=50M -> A, B trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g2_03_raise_liquidity_floor_200m(self):
        """Raising liquidity_floor to 200M filters out B (100M), C, D."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group2_volume_levels()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 200_000_000,
        }
        _print_test_header(
            'Group 2: Volume Levels', 'liquidity_floor=200M -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g2_04_raise_liquidity_floor_1b(self):
        """Raising liquidity_floor to 1B means nothing triggers."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group2_volume_levels()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 1_000_000_000,
        }
        _print_test_header(
            'Group 2: Volume Levels', 'liquidity_floor=1B -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g2_05_raise_rel_vol_min(self):
        """
        Raising rel_vol_min to 5.0 filters items whose bucket vol / EWMA
        expected vol is below 5.  Since expected_vol is initialised to the
        first observed bucket_vol (from call 1), and call 2 sees the same
        buckets, rel_vol ~ 1.0 for all items.  Nothing triggers.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group2_volume_levels()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_rel_vol_min': 5.0,
            'dump_liquidity_floor': 100,
        }
        _print_test_header(
            'Group 2: Volume Levels',
            'rel_vol_min=5.0 (EWMA inited to current) -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 3: SELL PRESSURE GRADIENT
    # Tests: sell_ratio_min at various thresholds
    # =========================================================================

    def test_g3_01_sell_ratio_40_all_trigger(self):
        """sell_ratio_min=0.40 -> all 4 items trigger (even D at 50%)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group3_sell_pressure()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_sell_ratio_min': 0.40,
        }
        _print_test_header(
            'Group 3: Sell Pressure', 'sell_ratio_min=0.40 -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g3_02_sell_ratio_55_filters_balanced(self):
        """sell_ratio_min=0.55 -> Item D (50% sell) filtered out."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group3_sell_pressure()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_sell_ratio_min': 0.55,
        }
        _print_test_header(
            'Group 3: Sell Pressure', 'sell_ratio_min=0.55 -> A, B, C trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID), str(ITEM_C_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g3_03_sell_ratio_70_filters_mild(self):
        """sell_ratio_min=0.70 -> Item C (65%) and D (50%) filtered out."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group3_sell_pressure()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_sell_ratio_min': 0.70,
        }
        _print_test_header(
            'Group 3: Sell Pressure', 'sell_ratio_min=0.70 -> A, B trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g3_04_sell_ratio_90_only_extreme(self):
        """sell_ratio_min=0.90 -> only Item A (95% sell) triggers."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group3_sell_pressure()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_sell_ratio_min': 0.90,
        }
        _print_test_header(
            'Group 3: Sell Pressure', 'sell_ratio_min=0.90 -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g3_05_sell_ratio_99_none_trigger(self):
        """sell_ratio_min=0.99 -> nothing triggers (even A is only 95%)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group3_sell_pressure()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_sell_ratio_min': 0.99,
        }
        _print_test_header(
            'Group 3: Sell Pressure', 'sell_ratio_min=0.99 -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 4: MARKET-WIDE SELL-OFF VS IDIOSYNCRATIC DUMP
    # Tests: shock_sigma with market drift stripping
    # =========================================================================

    def test_g4_01_loose_shock_all_droppers_trigger(self):
        """
        Force drift=0, shock_sigma=-0.5 -> all 4 dropping items trigger
        because each item's full log return counts as idiosyncratic.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group4_market_selloff()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_shock_sigma': -0.5,
        }
        _print_test_header(
            'Group 4: Market Sell-Off',
            'drift=0, shock_sigma=-0.5 -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        # Call 1: init EWMA state with normal prices
        cmd.compute_market_drift(normal_prices)
        cmd.check_dump_alert(alert, normal_prices)
        alert.refresh_from_db()
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        # Force drift to 0 so all drops register as idiosyncratic
        cmd.dump_market_state['market_drift'] = 0.0
        cmd.dump_market_state['last_mids'] = {
            str(i): 1000.0 for i in items
        }
        alert.refresh_from_db()
        result = cmd.check_dump_alert(alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g4_02_moderate_shock_filters_market_followers(self):
        """
        shock_sigma=-2.0 with market drift subtracted.

        Market drift ~ log(0.95) ~ -0.051 (median of three -5% drops).
        Item A: r = log(0.80) ~ -0.223, r_idio = -0.223 - (-0.051) = -0.172
                shock_sigma = -0.172 / sqrt(seeded_var) which is a huge negative
        Items B,C,D: r ~ -0.051, r_idio ~ 0.0, shock_sigma ~ 0

        Only Item A's idiosyncratic shock exceeds -2.0.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group4_market_selloff()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_shock_sigma': -2.0,
        }
        _print_test_header(
            'Group 4: Market Sell-Off',
            'shock_sigma=-2.0, drift strips market -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        _run_dump_check(cmd, alert, normal_prices)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        result = _run_dump_check(cmd, alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g4_03_tight_shock_sigma_none(self):
        """
        shock_sigma=-100 is so extreme that even Item A's big drop doesn't
        produce a sigma that negative. Nothing triggers.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group4_market_selloff()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_shock_sigma': -100.0,
        }
        _print_test_header(
            'Group 4: Market Sell-Off',
            'shock_sigma=-100 -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        _run_dump_check(cmd, alert, normal_prices)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        result = _run_dump_check(cmd, alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g4_04_zero_drift_all_shocks_hit(self):
        """
        Force market drift to 0 (don't compute it from prices) so ALL items'
        full drops count as idiosyncratic. With loose shock_sigma=-0.5, all trigger.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group4_market_selloff()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_shock_sigma': -0.5,
        }
        _print_test_header(
            'Group 4: Market Sell-Off',
            'Force drift=0, shock_sigma=-0.5 -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        # Call 1: use normal prices for EWMA init only
        cmd.compute_market_drift(normal_prices)
        cmd.check_dump_alert(alert, normal_prices)
        alert.refresh_from_db()
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        # Force drift to 0 so all drops are idiosyncratic
        cmd.dump_market_state['market_drift'] = 0.0
        cmd.dump_market_state['last_mids'] = {
            str(i): 1000.0 for i in items
        }
        alert.refresh_from_db()
        result = cmd.check_dump_alert(alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g4_05_custom_drift_isolates_outlier(self):
        """
        Manually set drift = log(0.95) so items dropping 5% have r_idio ~ 0
        and only the 20% dropper has a large negative idiosyncratic return.
        shock_sigma=-5.0 requires a very strong signal.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group4_market_selloff()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_shock_sigma': -5.0,
        }
        _print_test_header(
            'Group 4: Market Sell-Off',
            'Manual drift=log(0.95), shock_sigma=-5.0 -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        cmd.compute_market_drift(normal_prices)
        cmd.check_dump_alert(alert, normal_prices)
        alert.refresh_from_db()
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        # Set drift to exactly log(0.95) to neutralise 5% drops
        cmd.dump_market_state['market_drift'] = math.log(0.95)
        cmd.dump_market_state['last_mids'] = {
            str(i): 1000.0 for i in items
        }
        alert.refresh_from_db()
        result = cmd.check_dump_alert(alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 5: CONSISTENCY CHECK SCENARIOS
    # Tests: consistency_required flag and the 6-of-12 two-sided rule
    # =========================================================================

    def test_g5_01_consistency_off_all_trigger(self):
        """With consistency_required=False, all 4 items trigger regardless."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group5_consistency()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_consistency_required': False,
        }
        _print_test_header(
            'Group 5: Consistency', 'consistency off -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g5_02_consistency_on_filters_below_6(self):
        """
        With consistency_required=True, items C (5/12) and D (2/12) fail
        the 6-of-12 rule.  Only A (12/12) and B (7/12) trigger.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group5_consistency()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_consistency_required': True,
        }
        _print_test_header(
            'Group 5: Consistency',
            'consistency on -> A (12/12), B (7/12) trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g5_03_consistency_on_and_tight_discount(self):
        """
        consistency on + discount_min=8% -> only A triggers (B's discount
        is ~12% which passes, but let's verify both gates work together).

        Actually all items have the same avg_low (880) and fair ~ 1000, so
        discount ~ 12% for all.  With consistency on, A and B pass.
        Adding discount_min=8% doesn't filter further (both > 8%).
        So A and B still trigger.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group5_consistency()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_consistency_required': True,
            'dump_discount_min': 8.0,
        }
        _print_test_header(
            'Group 5: Consistency',
            'consistency on + discount_min=8% -> A, B trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g5_04_consistency_on_tight_sell_ratio(self):
        """
        consistency on + sell_ratio=0.90 -> no item triggers because
        all have 85% sell ratio (170/200).  0.90 > 0.85.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group5_consistency()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_consistency_required': True,
            'dump_sell_ratio_min': 0.90,
        }
        _print_test_header(
            'Group 5: Consistency',
            'consistency on + sell_ratio=0.90 -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g5_05_consistency_off_tight_sell_ratio(self):
        """
        consistency off + sell_ratio=0.90 -> none trigger.
        Even with consistency bypassed, the sell ratio gate still blocks.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group5_consistency()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_consistency_required': False,
            'dump_sell_ratio_min': 0.90,
        }
        _print_test_header(
            'Group 5: Consistency',
            'consistency off + sell_ratio=0.90 -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 6: COOLDOWN & CONFIRMATION
    # Tests: dump_confirmation_buckets and dump_cooldown behavior
    # =========================================================================

    def test_g6_01_confirmation_1_triggers_immediately(self):
        """confirmation_buckets=1 -> both items trigger on first valid pass."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group6_cooldown_confirmation()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_confirmation_buckets': 1,
            'dump_cooldown': 0,
        }
        _print_test_header(
            'Group 6: Cooldown & Confirmation',
            'confirmation=1 -> both trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g6_02_confirmation_2_needs_two_passes(self):
        """
        confirmation_buckets=2 -> nothing triggers on call 2 alone because
        consecutive=1 < 2.  Need a 3rd call to trigger.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group6_cooldown_confirmation()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_confirmation_buckets': 2,
            'dump_cooldown': 0,
        }
        _print_test_header(
            'Group 6: Cooldown & Confirmation',
            'confirmation=2 -> nothing on call 2 (consecutive=1)',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        # Standard 2-cycle: call 1 init, call 2 first valid pass
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g6_03_confirmation_2_third_call_triggers(self):
        """
        confirmation_buckets=2 -> call 3 with continuing dump prices triggers
        both items because consecutive reaches 2.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group6_cooldown_confirmation()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_confirmation_buckets': 2,
            'dump_cooldown': 0,
        }
        _print_test_header(
            'Group 6: Cooldown & Confirmation',
            'confirmation=2 -> call 3 triggers both',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()

        # Call 1: init
        _run_dump_check(cmd, alert, normal_prices)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))

        # Call 2: first valid pass (consecutive becomes 1)
        _run_dump_check(cmd, alert, dumped_prices)

        # Re-seed var_idio because call 2 updated it with the big return
        # We want call 3 to still see a meaningful shock relative to
        # historical (small) variance
        for item_id in items:
            _seed_var_idio(alert, str(item_id))

        # Need to set last_mids back so the prices still look like a drop
        # on call 3. We set them to "normal" so the dump prices register.
        state = json.loads(alert.dump_state) if alert.dump_state else {}
        for item_id in items:
            s = str(item_id)
            if s in state:
                state[s]['last_mid'] = 1000.0
        alert.dump_state = json.dumps(state)
        alert.save(update_fields=['dump_state'])

        # Call 3: second consecutive pass -> triggers
        result = _run_dump_check(cmd, alert, dumped_prices)
        triggered = _triggered_item_ids(result)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g6_04_cooldown_blocks_retrigger(self):
        """
        After triggering with confirmation=1, the cooldown (set to 60 min)
        prevents re-triggering on the very next check cycle.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group6_cooldown_confirmation()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_confirmation_buckets': 1,
            'dump_cooldown': 60,
        }
        _print_test_header(
            'Group 6: Cooldown & Confirmation',
            'cooldown=60min -> retrigger blocked',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()

        # Call 1: init
        _run_dump_check(cmd, alert, normal_prices)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))

        # Call 2: triggers and sets cooldown_until
        result2 = _run_dump_check(cmd, alert, dumped_prices)
        triggered2 = _triggered_item_ids(result2)
        # Verify it DID trigger first
        self.assertEqual(triggered2, {str(ITEM_A_ID), str(ITEM_B_ID)})

        # Now re-seed and attempt call 3 immediately (within cooldown window)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        state = json.loads(alert.dump_state) if alert.dump_state else {}
        for item_id in items:
            s = str(item_id)
            if s in state:
                state[s]['last_mid'] = 1000.0
        alert.dump_state = json.dumps(state)
        alert.save(update_fields=['dump_state'])

        # Call 3: should be blocked by cooldown
        result3 = _run_dump_check(cmd, alert, dumped_prices)
        triggered3 = _triggered_item_ids(result3)

        _print_result(set(), triggered3)
        self.assertEqual(triggered3, set())

    def test_g6_05_cooldown_0_allows_immediate_retrigger(self):
        """
        cooldown=0 means items can re-trigger on consecutive cycles.
        After triggering on call 2, call 3 triggers again.
        """
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group6_cooldown_confirmation()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_confirmation_buckets': 1,
            'dump_cooldown': 0,
        }
        _print_test_header(
            'Group 6: Cooldown & Confirmation',
            'cooldown=0 -> retrigger allowed',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()

        # Call 1: init
        _run_dump_check(cmd, alert, normal_prices)
        for item_id in items:
            _seed_var_idio(alert, str(item_id))

        # Call 2: first trigger
        _run_dump_check(cmd, alert, dumped_prices)

        # Re-seed for call 3
        for item_id in items:
            _seed_var_idio(alert, str(item_id))
        state = json.loads(alert.dump_state) if alert.dump_state else {}
        for item_id in items:
            s = str(item_id)
            if s in state:
                state[s]['last_mid'] = 1000.0
        alert.dump_state = json.dumps(state)
        alert.save(update_fields=['dump_state'])

        # Call 3: re-trigger with cooldown=0
        result3 = _run_dump_check(cmd, alert, dumped_prices)
        triggered3 = _triggered_item_ids(result3)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered3)
        self.assertEqual(triggered3, expected)

    # =========================================================================
    # GROUP 7: EXTREME VS MARGINAL DISCOUNTS
    # Tests: discount_min at 1%, 3%, 5%, 10% thresholds
    # =========================================================================

    def test_g7_01_discount_min_0_5_all_trigger(self):
        """discount_min=0.5% -> all 4 items trigger (even D at ~1%)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group7_discount_gradient()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_discount_min': 0.5,
        }
        _print_test_header(
            'Group 7: Discount Gradient', 'discount_min=0.5% -> all trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer',
             'Bandos chestplate'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(i) for i in items}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g7_02_discount_min_2_filters_marginal(self):
        """discount_min=2% -> Item D (1% discount) filtered out."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group7_discount_gradient()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_discount_min': 2.0,
        }
        _print_test_header(
            'Group 7: Discount Gradient', 'discount_min=2% -> A, B, C trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID), str(ITEM_C_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g7_03_discount_min_4_filters_borderline(self):
        """discount_min=4% -> Items C (3%) and D (1%) filtered out."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group7_discount_gradient()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_discount_min': 4.0,
        }
        _print_test_header(
            'Group 7: Discount Gradient', 'discount_min=4% -> A, B trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g7_04_discount_min_10_only_extreme(self):
        """discount_min=10% -> only Item A (15% discount) triggers."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group7_discount_gradient()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_discount_min': 10.0,
        }
        _print_test_header(
            'Group 7: Discount Gradient', 'discount_min=10% -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g7_05_discount_min_20_none(self):
        """discount_min=20% -> nothing triggers (max discount is 15%)."""
        normal_prices, dumped_prices, db_items, items = \
            self._setup_group7_discount_gradient()

        alert_params = {
            'item_ids': json.dumps(items),
            'dump_discount_min': 20.0,
        }
        _print_test_header(
            'Group 7: Discount Gradient', 'discount_min=20% -> none trigger',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, items)

        expected = set()
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    # =========================================================================
    # GROUP 8: ALL-ITEMS MODE VS SPECIFIC ITEMS
    # Tests: is_all_items, item_ids (multi), single item_id scope modes
    # =========================================================================

    def test_g8_01_all_items_mode_finds_dumpers(self):
        """
        is_all_items=True -> alert scans all 5 items, finds 3 dumping.
        """
        normal_prices, dumped_prices, db_items, all_items = \
            self._setup_group8_scope_modes()

        alert_params = {
            'is_all_items': True,
        }
        _print_test_header(
            'Group 8: Scope Modes', 'is_all_items=True -> 3 dumpers found',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon crossbow', 'Dragon warhammer'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, all_items)

        expected = {str(ITEM_A_ID), str(ITEM_B_ID), str(ITEM_C_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g8_02_multi_item_specific_subset(self):
        """
        item_ids=[A, C] -> only checks those two.  Both are dumping, so both trigger.
        """
        normal_prices, dumped_prices, db_items, all_items = \
            self._setup_group8_scope_modes()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_C_ID]),
        }
        _print_test_header(
            'Group 8: Scope Modes', 'item_ids=[A, C] -> both trigger',
            db_items, alert_params,
            ['Abyssal whip', 'Dragon warhammer'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, all_items)

        expected = {str(ITEM_A_ID), str(ITEM_C_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g8_03_multi_item_includes_stable(self):
        """
        item_ids=[A, D] -> A is dumping, D is stable.  Only A triggers.
        """
        normal_prices, dumped_prices, db_items, all_items = \
            self._setup_group8_scope_modes()

        alert_params = {
            'item_ids': json.dumps([ITEM_A_ID, ITEM_D_ID]),
        }
        _print_test_header(
            'Group 8: Scope Modes', 'item_ids=[A, D] -> only A triggers',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        _, triggered = self._run_two_cycle_check(
            alert, normal_prices, dumped_prices, all_items)

        expected = {str(ITEM_A_ID)}
        _print_result(expected, triggered)
        self.assertEqual(triggered, expected)

    def test_g8_04_single_item_dumping(self):
        """
        Single item_id=A (dumping) -> returns True.
        """
        normal_prices, dumped_prices, db_items, all_items = \
            self._setup_group8_scope_modes()

        alert_params = {
            'item_id': ITEM_A_ID,
        }
        _print_test_header(
            'Group 8: Scope Modes', 'single item_id=A (dumping) -> True',
            db_items, alert_params,
            ['Abyssal whip'],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        _run_dump_check(cmd, alert, normal_prices)
        _seed_var_idio(alert, str(ITEM_A_ID))
        result = _run_dump_check(cmd, alert, dumped_prices)

        _print_result({'single'}, _triggered_item_ids(result))
        self.assertTrue(result)

    def test_g8_05_single_item_stable(self):
        """
        Single item_id=D (stable) -> returns False.
        """
        normal_prices, dumped_prices, db_items, all_items = \
            self._setup_group8_scope_modes()

        alert_params = {
            'item_id': ITEM_D_ID,
        }
        _print_test_header(
            'Group 8: Scope Modes', 'single item_id=D (stable) -> False',
            db_items, alert_params,
            [],
        )
        alert = self._create_alert(**alert_params)
        cmd = _make_command()
        _run_dump_check(cmd, alert, normal_prices)
        _seed_var_idio(alert, str(ITEM_D_ID))
        result = _run_dump_check(cmd, alert, dumped_prices)

        _print_result(set(), _triggered_item_ids(result))
        self.assertFalse(result)

