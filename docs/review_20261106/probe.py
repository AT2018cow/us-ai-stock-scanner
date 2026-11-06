"""Offline audit reproductions; run with PYTHONPATH=src .venv/bin/python this_file."""
import inspect
from ai_value_scanner.fundamentals.accounting import derive_accounting_metrics, fundamental_quality_score_from_metrics
from ai_value_scanner.decision.quality import build_company_quality_v2
from ai_value_scanner.features.price import compute_price_history_features
kw = dict.fromkeys(inspect.signature(derive_accounting_metrics).parameters)
kw.update(debt_long_term=100, debt_current=0, cash_and_equivalents=0, adjusted_ebitda=-10)
metrics = derive_accounting_metrics(**kw)
print('R01 leverage:', metrics['net_debt_to_ebitda'])
print('R01 risks:', [(x.code, x.value) for x in build_company_quality_v2(metrics).risks])
print('R01 positives:', [(x.code, x.value) for x in build_company_quality_v2(metrics).positives])
print('R02 all-NaN score:', fundamental_quality_score_from_metrics(*([float('nan')] * 5)))
result = compute_price_history_features(current_price=100, range_highs=[110], range_lows=[90], closes=[100]*30+[float('nan')]+[100]*30, dollar_volumes=[1000]*20)
print('R03 incomplete-window volatility:', result['volatility_60d'])

assert metrics["net_debt_to_ebitda"] is None
assert any(x.code == "net_debt_nonpositive_ebitda" for x in build_company_quality_v2(metrics).risks)
assert fundamental_quality_score_from_metrics(*([float("nan")]*5)) == .5
assert result["volatility_60d"] is None
