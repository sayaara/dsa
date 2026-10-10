# -*- coding: utf-8 -*-
"""
===================================
Stock watchlist intelligent analysis system - environment verification
===================================

Verifies that the .env configuration is correct, covering:
1. Configuration loading
2. Database inspection
3. Data source checks
4. LLM call check
5. Notification push check

Usage:
    python scripts/check_env.py              # run every check
    python scripts/check_env.py --db         # inspect the database only
    python scripts/check_env.py --llm        # check the LLM only
    python scripts/check_env.py --fetch      # check the data fetch only
    python scripts/check_env.py --notify     # check notifications only

"""
import os
# Proxy config - controlled by USE_PROXY env var, off by default.
# Set USE_PROXY=true in .env if you need a local proxy (e.g. behind a corporate proxy).
# GitHub Actions always skips this regardless of USE_PROXY.
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

import argparse
import logging
import sys
from datetime import datetime, date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _reconfigure_output_stream(stream):
    """Avoid UnicodeEncodeError on legacy Windows console code pages."""
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return

    for kwargs in (
        {"encoding": "utf-8", "errors": "replace"},
        {"errors": "replace"},
    ):
        try:
            reconfigure(**kwargs)
            return
        except Exception:
            continue


def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        _reconfigure_output_stream(stream)


# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def print_header(title: str):
    """Print a heading"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_section(title: str):
    """Print a subsection heading"""
    print(f"\n--- {title} ---")


def check_config():
    """Check that the configuration loads"""
    print_header("1. Configuration")

    from src.config import get_config
    config = get_config()

    print_section("Basic settings")
    print(f"  Watchlist: {config.stock_list}")
    print(f"  Database path: {config.database_path}")
    print(f"  Max workers: {config.max_workers}")
    print(f"  Debug mode: {config.debug}")

    print_section("LLM settings")
    print(f"  LITELLM_MODEL: {config.litellm_model or 'not set'}")
    print(f"  Gemini API key: {'set ✓' if config.gemini_api_key else 'not set'}")
    if config.gemini_api_key:
        print(f"    Key prefix: {config.gemini_api_key[:8]}...")
    print(f"  Gemini primary model: {config.gemini_model}")
    print(f"  Gemini fallback model: {config.gemini_model_fallback}")

    from src.notification import NotificationService
    _channels = NotificationService.detect_configured_channels(config)
    print(f"  Notification channels: {', '.join(c.value for c in _channels) if _channels else 'none configured ✗'}")

    print_section("Validation")
    issues = config.validate_structured()
    _prefix = {"error": "  ✗", "warning": "  ⚠", "info": "  ·"}
    for issue in issues:
        print(f"{_prefix.get(issue.severity, '  ?')} [{issue.severity.upper()}] {issue.message}")
    if not any(i.severity in ("error", "warning") for i in issues):
        print("  ✓ Required settings are valid")

    return True


def view_database():
    """Inspect the database contents"""
    print_header("2. Database")

    from src.storage import get_db
    from sqlalchemy import text

    db = get_db()

    print_section("Connection")
    print("  ✓ Connected")

    # Query through a dedicated session
    session = db.get_session()
    try:
        # Statistics
        result = session.execute(text("""
            SELECT
                code,
                COUNT(*) as count,
                MIN(date) as min_date,
                MAX(date) as max_date,
                data_source
            FROM stock_daily
            GROUP BY code
            ORDER BY code
        """))
        stocks = result.fetchall()

        print_section(f"Stored stock data ({len(stocks)} symbols)")
        if stocks:
            print(f"  {'Symbol':<10} {'Rows':<8} {'First date':<12} {'Last date':<12} {'Source'}")
            print("  " + "-" * 60)
            for row in stocks:
                print(f"  {row[0]:<10} {row[1]:<8} {row[2]!s:<12} {row[3]!s:<12} {row[4] or 'Unknown'}")
        else:
            print("  No data yet")

        # Query today's data
        today = date.today()
        result = session.execute(text("""
            SELECT code, date, open, high, low, close, pct_chg, volume, ma5, ma10, ma20, volume_ratio
            FROM stock_daily
            WHERE date = :today
            ORDER BY code
        """), {"today": today})
        today_data = result.fetchall()

        print_section(f"Today's data ({today})")
        if today_data:
            for row in today_data:
                code, dt, open_, high, low, close, pct_chg, volume, ma5, ma10, ma20, vol_ratio = row
                print(f"\n  [{code}]")
                print(f"    Open: {open_:.2f}  High: {high:.2f}  Low: {low:.2f}  Close: {close:.2f}")
                print(f"    Change: {pct_chg:.2f}%  Volume: {volume/1e6:.2f}M shares")
                print(f"    MA5: {ma5:.2f}  MA10: {ma10:.2f}  MA20: {ma20:.2f}  Volume ratio: {vol_ratio:.2f}")
        else:
            print("  No data for today")

        # Query the 10 most recent rows
        result = session.execute(text("""
            SELECT code, date, close, pct_chg, volume, data_source
            FROM stock_daily
            ORDER BY date DESC, code
            LIMIT 10
        """))
        recent = result.fetchall()

        print_section("10 most recent rows")
        if recent:
            print(f"  {'Symbol':<10} {'Date':<12} {'Close':<10} {'Chg %':<8} {'Volume':<15} {'Source'}")
            print("  " + "-" * 70)
            for row in recent:
                vol_str = f"{row[4]/1e6:.2f}M" if row[4] else "N/A"
                print(f"  {row[0]:<10} {row[1]!s:<12} {row[2]:<10.2f} {row[3]:<8.2f} {vol_str:<15} {row[5] or 'Unknown'}")
    finally:
        session.close()

    return True


def check_data_fetch(stock_code: str = "AAPL"):
    """Check the data fetch"""
    print_header("3. Data fetch")

    from data_provider import DataFetcherManager

    manager = DataFetcherManager()

    print_section("Data sources")
    for i, name in enumerate(manager.available_fetchers, 1):
        print(f"  {i}. {name}")

    print_section(f"Fetching {stock_code}")
    print("  Fetching (this can take a few seconds)...")

    try:
        df, source = manager.get_daily_data(stock_code, days=5)

        print("  ✓ Fetched")
        print(f"    Source: {source}")
        print(f"    Rows: {len(df)}")

        print_section("Preview (last 5 rows)")
        if not df.empty:
            preview_cols = ['date', 'open', 'high', 'low', 'close', 'pct_chg', 'volume']
            existing_cols = [c for c in preview_cols if c in df.columns]
            print(df[existing_cols].tail().to_string(index=False))

        return True

    except Exception as e:
        print(f"  ✗ Fetch failed: {e}")
        return False


def check_llm():
    """Check the LLM call"""
    print_header("4. LLM call")

    from src.analyzer import GeminiAnalyzer
    from src.config import get_config
    import time

    config = get_config()

    print_section("Model")
    print(f"  LITELLM_MODEL: {config.litellm_model or 'not set (legacy Gemini settings are used)'}")
    if not config.litellm_model:
        print(f"  Gemini primary model: {config.gemini_model}")
        print(f"  Gemini fallback model: {config.gemini_model_fallback}")

    analyzer = GeminiAnalyzer()

    print_section("Initialization")
    if analyzer.is_available():
        print("  ✓ Model is available")
    else:
        print("  ✗ No usable model (check the API key and LITELLM_MODEL)")
        return False

    # Build the test context
    test_context = {
        'code': 'AAPL',
        'date': date.today().isoformat(),
        'today': {
            'open': 228.0,
            'high': 231.5,
            'low': 227.2,
            'close': 230.4,
            'volume': 52000000,
            'amount': 11980800000,
            'pct_chg': 0.56,
            'ma5': 229.6,
            'ma10': 228.1,
            'ma20': 226.4,
            'volume_ratio': 1.1,
        },
        'ma_status': 'Bullish alignment 📈',
        'volume_change_ratio': 1.05,
        'price_change_ratio': 0.56,
    }

    print_section("Test request")
    print("  Test stock: Apple (AAPL), sample data")
    print("  Calling the model...")

    start_time = time.time()

    try:
        result = analyzer.analyze(test_context)

        elapsed = time.time() - start_time
        print(f"\n  ✓ Call succeeded ({elapsed:.2f}s)")

        print_section("Result")
        print(f"  Sentiment score: {result.sentiment_score}/100")
        print(f"  Trend: {result.trend_prediction}")
        print(f"  Advice: {result.operation_advice}")
        print(f"  Technical: {result.technical_analysis[:80]}..." if len(result.technical_analysis) > 80 else f"  Technical: {result.technical_analysis}")
        print(f"  News: {result.news_summary[:80]}..." if len(result.news_summary) > 80 else f"  News: {result.news_summary}")
        print(f"  Summary: {result.analysis_summary}")

        if not result.success:
            print(f"\n  ⚠ Note: {result.error_message}")

        return result.success

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ✗ Call failed ({elapsed:.2f}s)")
        print(f"  Error: {e}")

        # Give a more detailed error hint
        error_str = str(e).lower()
        if 'timeout' in error_str or 'unavailable' in error_str:
            print("\n  Diagnosis: network timeout. Possible causes:")
            print("    1. No route to the provider (a proxy may be needed: HTTPS_PROXY=http://host:port)")
            print("    2. The provider is temporarily unavailable")
            print("    3. Rate limiting")
        elif 'invalid' in error_str or 'api key' in error_str:
            print("\n  Diagnosis: the API key may be invalid")
        elif 'model' in error_str:
            print("\n  Diagnosis: the model name may be wrong; check LITELLM_MODEL in .env")

        return False


def check_notification():
    """Check the notification push"""
    print_header("5. Notifications")

    from src.notification import NotificationService
    from src.config import get_config

    get_config()
    service = NotificationService()

    print_section("Configuration")
    if service.is_available():
        print(f"  ✓ Channels configured: {service.get_channel_names()}")
    else:
        print("  ✗ No notification channel is configured")
        return False

    print_section("Test message")

    test_message = f"""## 🧪 Test message

This is a test message from the **Stock Watchlist Analysis System**.

- Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Purpose: check the notification channel settings

If you received this message, notifications are configured correctly ✓"""

    print("  Sending...")

    try:
        success = service.send(test_message)

        if success:
            print("  ✓ Sent; check your configured channels")
        else:
            print("  ✗ Sending failed")

        return success

    except Exception as e:
        print(f"  ✗ Sending raised an error: {e}")
        return False


def run_all_tests():
    """Run every check"""
    print("\n" + "🚀" * 20)
    print("  Stock Watchlist Analysis System - environment check")
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("🚀" * 20)

    results = {}

    # 1. Configuration check
    try:
        results['Configuration'] = check_config()
    except Exception as e:
        print(f"  ✗ Configuration check failed: {e}")
        results['Configuration'] = False

    # 2. Database inspection
    try:
        results['Database'] = view_database()
    except Exception as e:
        print(f"  ✗ Database check failed: {e}")
        results['Database'] = False

    # 3. Data fetch (skipped, it is too slow)
    # results['Data fetch'] = check_data_fetch()

    # 4. LLM check (optional)
    # results['LLM call'] = check_llm()

    # Summary
    print_header("Summary")
    for name, passed in results.items():
        status = "✓ passed" if passed else "✗ failed"
        print(f"  {status}: {name}")

    print("\nTip: --llm checks the LLM call")
    print("Tip: --fetch checks the data fetch")
    print("Tip: --notify sends a test notification")


def query_stock_data(stock_code: str, days: int = 10):
    """Query the data for a given stock"""
    print_header(f"Stored data: {stock_code}")

    from src.storage import get_db
    from sqlalchemy import text

    db = get_db()

    session = db.get_session()
    try:
        result = session.execute(text("""
            SELECT date, open, high, low, close, pct_chg, volume, amount, ma5, ma10, ma20, volume_ratio
            FROM stock_daily
            WHERE code = :code
            ORDER BY date DESC
            LIMIT :limit
        """), {"code": stock_code, "limit": days})

        rows = result.fetchall()

        if rows:
            print(f"\n  {len(rows)} most recent rows:\n")
            print(f"  {'Date':<12} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Chg %':<8} {'MA5':<10} {'MA10':<10} {'Vol ratio':<8}")
            print("  " + "-" * 100)
            for row in rows:
                dt, open_, high, low, close, pct_chg, vol, amt, ma5, ma10, ma20, vol_ratio = row
                print(f"  {dt!s:<12} {open_:<10.2f} {high:<10.2f} {low:<10.2f} {close:<10.2f} {pct_chg:<8.2f} {ma5:<10.2f} {ma10:<10.2f} {vol_ratio:<8.2f}")
        else:
            print(f"  No data found for {stock_code}")
    finally:
        session.close()


def main():
    configure_console_encoding()

    parser = argparse.ArgumentParser(
        description='Stock Watchlist Analysis System - environment check',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('--db', action='store_true', help='inspect the database')
    parser.add_argument('--llm', action='store_true', help='check the LLM call')
    parser.add_argument('--fetch', action='store_true', help='check the data fetch (AAPL)')
    parser.add_argument('--notify', action='store_true', help='send a test notification')
    parser.add_argument('--config', action='store_true', help='show the configuration')
    parser.add_argument('--stock', type=str, help='show stored data for a symbol, for example --stock AAPL')
    parser.add_argument('--all', action='store_true', help='run every check, including the LLM call')

    args = parser.parse_args()

    # Run the basic checks when no argument is supplied
    if not any([args.db, args.llm, args.fetch, args.notify, args.config, args.stock, args.all]):
        run_all_tests()
        return 0

    # Run the checks the arguments select
    if args.config:
        check_config()

    if args.db:
        view_database()

    if args.stock:
        query_stock_data(args.stock)

    if args.fetch:
        check_data_fetch()

    if args.llm:
        check_llm()

    if args.notify:
        check_notification()

    if args.all:
        check_config()
        view_database()
        check_data_fetch()
        check_llm()
        check_notification()

    return 0


if __name__ == "__main__":
    sys.exit(main())
