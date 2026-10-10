#!/bin/bash
# ===================================
# US/Canada stock analysis system - test script
# ===================================
#
# Usage:
#   ./scripts/test.sh [scenario]
#
# Scenarios:
#   market      - market review only
#   ca-stock    - Canada analysis (RY.TO, SHOP.TO)
#   us-stock    - US analysis (AAPL)
#   mixed       - mixed-market analysis
#   single      - single-stock notification mode
#   dry-run     - fetch data only, no AI analysis
#   full        - full run (stocks and market review)
#   quick       - quick test (one stock)
#   all         - run all tests
#   (also: code, yfinance, syntax, flake8; see --help)
#
# Examples:
#   ./scripts/test.sh market      # market review
#   ./scripts/test.sh us-stock    # US analysis
#   ./scripts/test.sh quick       # quick test
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Coloured output helpers
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

header() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}$1${NC}"
    echo "=============================================="
    echo ""
}

# Check the Python environment
check_python() {
    if ! command -v python3 &> /dev/null; then
        error "python3 is not installed"
        exit 1
    fi
    info "Python version: $(python3 --version)"
}

# Check dependencies
check_deps() {
    info "Checking dependencies..."
    python3 -c "import yfinance" 2>/dev/null || { warn "yfinance is not installed; the US and Canada tests may fail"; }
    success "Dependency check finished"
}

# ==================== Scenarios ====================

# Test 1: market review
test_market() {
    header "Test scenario: market review"
    info "Running the market review..."
    python3 main.py --market-review "$@"
    success "Market review test finished"
}

# Test 3: Canada analysis
test_ca_stock() {
    header "Test scenario: Canada analysis"
    info "Analyzing Canadian stocks: RY.TO (Royal Bank of Canada), SHOP.TO (Shopify)"
    python3 main.py --stocks RY.TO,SHOP.TO --no-market-review "$@"
    success "Canada analysis test finished"
}

# Test 4: US analysis
test_us_stock() {
    header "Test scenario: US analysis"
    info "Analyzing a US stock: AAPL (Apple)"
    # Extra arguments are passed through; --no-notify is not added by default
    python3 main.py --stocks AAPL --no-market-review "$@"
    success "US analysis test finished"
}

# Test 5: mixed markets
test_mixed() {
    header "Test scenario: mixed-market analysis"
    info "Analyzing mixed markets: RY.TO (Canada), AAPL (US), MSFT (US)"
    python3 main.py --stocks RY.TO,AAPL,MSFT --no-market-review
    success "Mixed-market test finished"
}

# Test 6: single-stock notification mode
test_single() {
    header "Test scenario: single-stock notification mode"
    info "Testing single-stock notification mode..."
    python3 main.py --stocks AAPL --single-notify --no-market-review
    success "Single-stock notification test finished"
}

# Test 7: dry-run mode
test_dry_run() {
    header "Test scenario: dry-run mode"
    info "Fetching data only, no AI analysis..."
    python3 main.py --stocks AAPL,MSFT --dry-run --no-notify
    success "Dry-run test finished"
}

# Test 8: full run
test_full() {
    header "Test scenario: full run"
    info "Running the full analysis (stocks and market review)..."
    python3 main.py --stocks AAPL --no-notify
    success "Full run test finished"
}

# Test 9: quick test
test_quick() {
    header "Test scenario: quick test"
    info "Quick test with one stock..."
    python3 main.py --stocks AAPL --no-market-review --no-notify "$@"
    success "Quick test finished"
}

# Test 10: symbol recognition
test_code_recognition() {
    header "Test scenario: symbol recognition"
    info "Testing stock symbol recognition..."

    python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')
from data_provider.market_codes import is_us_code as _is_us_code
from src.services.market_symbol_utils import get_suffix_market
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

test_cases = [
    # (code, expected US, expected suffix market, expected supported, description)
    ("AAPL", True, None, True, "US - Apple"),
    ("TSLA", True, None, True, "US - Tesla"),
    ("BRK.B", True, None, True, "US - Berkshire B"),
    ("RY.TO", False, "ca", True, "Canada - Royal Bank"),
    ("hk00700", False, None, False, "Hong Kong (not supported)"),
    ("0700.HK", False, None, False, "Hong Kong suffix (not supported)"),
]

print("\nStock code recognition:")
print("-" * 60)
all_pass = True
for code, exp_us, exp_suffix, exp_supported, desc in test_cases:
    is_us = _is_us_code(code)
    suffix_market = get_suffix_market(code)
    supported = parse_analysis_target(code).asset_type != ParseStatus.UNSUPPORTED
    ok = is_us == exp_us and suffix_market == exp_suffix and supported == exp_supported
    status = "✅" if ok else "❌"
    all_pass = all_pass and ok
    print(f"{status} {code:10} | US:{is_us!s:5} suffix:{suffix_market!s:5} supported:{supported!s:5} | {desc}")

print("-" * 60)
print(f"{'✅ All checks passed!' if all_pass else '❌ Some checks failed!'}")
sys.exit(0 if all_pass else 1)
PYTEST

    success "Symbol recognition test finished"
}

# Test 11: Yahoo Finance symbol conversion
test_yfinance_convert() {
    header "Test scenario: Yahoo Finance symbol conversion"
    info "Testing Yahoo Finance symbol conversion..."

    python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')
from data_provider.yfinance_fetcher import YfinanceFetcher

fetcher = YfinanceFetcher()

test_cases = [
    ("AAPL", "AAPL", "US"),
    ("tsla", "TSLA", "US, lowercase"),
    ("BRK.B", "BRK-B", "US share class"),
    ("RY.TO", "RY.TO", "Canada"),
    ("SPX", "^GSPC", "US index"),
]

print("\nYahoo Finance symbol conversion:")
print("-" * 60)
all_pass = True
for input_code, expected, desc in test_cases:
    result = fetcher._convert_stock_code(input_code)
    status = "✅" if result == expected else "❌"
    all_pass = all_pass and (result == expected)
    print(f"{status} {input_code:10} -> {result:12} (expected: {expected:12}) | {desc}")

print("-" * 60)
print(f"{'✅ All checks passed!' if all_pass else '❌ Some checks failed!'}")
sys.exit(0 if all_pass else 1)
PYTEST

    success "Yahoo Finance conversion test finished"
}

# Test 12: syntax check
test_syntax() {
    header "Test scenario: Python syntax check"
    info "Checking Python syntax..."

    python3 -m py_compile main.py src/config.py src/notification.py \
        data_provider/market_codes.py \
        data_provider/yfinance_fetcher.py \
        bot/commands/analyze.py

    success "Syntax check passed"
}

# Test 13: flake8 static check
test_flake8() {
    header "Test scenario: flake8 static check"
    info "Running flake8 for critical errors..."

    if command -v flake8 &> /dev/null; then
        flake8 main.py src/config.py src/notification.py --select=F821,E999 --max-line-length=120
        success "flake8 check passed"
    else
        warn "flake8 is not installed; skipping"
    fi
}

# Run all tests
test_all() {
    header "Running all tests"

    test_syntax
    test_code_recognition
    test_yfinance_convert
    test_flake8

    echo ""
    info "The following tests need network access and API keys and may fail:"
    echo ""

    test_dry_run || warn "Dry-run test failed (possibly a network problem)"
    test_quick || warn "Quick test failed (possibly an API problem)"

    success "All tests finished!"
}

# ==================== Main ====================

main() {
    header "US/Canada stock analysis system - tests"

    check_python
    check_deps

    case "${1:-help}" in
        market)
            shift
            test_market "$@"
            ;;
        ca-stock|ca_stock|castock|ca)
            shift
            test_ca_stock "$@"
            ;;
        us-stock|us_stock|usstock|us)
            shift
            test_us_stock "$@"
            ;;
        mixed|mix)
            shift
            test_mixed "$@"
            ;;
        single)
            shift
            test_single "$@"
            ;;
        dry-run|dryrun|dry)
            shift
            test_dry_run "$@"
            ;;
        full)
            shift
            test_full "$@"
            ;;
        quick|q)
            shift
            test_quick "$@"
            ;;
        code|recognition)
            shift
            test_code_recognition "$@"
            ;;
        yfinance|yf)
            shift
            test_yfinance_convert "$@"
            ;;
        syntax)
            shift
            test_syntax "$@"
            ;;
        flake8|lint)
            shift
            test_flake8 "$@"
            ;;
        all)
            shift
            test_all "$@"
            ;;
        help|--help|-h|*)
            echo "Usage: $0 [scenario]"
            echo ""
            echo "Scenarios:"
            echo "  market      - market review only"
            echo "  ca-stock    - Canada analysis"
            echo "  us-stock    - US analysis"
            echo "  mixed       - mixed-market analysis"
            echo "  single      - single-stock notification mode"
            echo "  dry-run     - fetch data only"
            echo "  full        - full run"
            echo "  quick       - quick test (recommended)"
            echo "  code        - symbol recognition test"
            echo "  yfinance    - Yahoo Finance conversion test"
            echo "  syntax      - syntax check"
            echo "  flake8      - static check"
            echo "  all         - run all tests"
            echo ""
            echo "Examples:"
            echo "  $0 quick     # quick test"
            echo "  $0 us-stock  # US analysis"
            echo "  $0 code      # symbol recognition"
            echo "  $0 all       # run all tests"
            ;;
    esac
}

main "$@"
