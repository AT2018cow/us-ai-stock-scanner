"""Build the Venture Sleeve universe (docs/multi_theme_expansion.md §6.3).

The venture sleeve (10x-hunter, P0 paper) universe is a three-layer funnel —
each layer is EARLIER in the institutional-thesis lifecycle than the last:

  L1  Theme ETF baskets (already built by build_theme_universe.py)
      filtered to the venture window: market cap $100M-$3B + daily dollar
      volume >= $500k. "Confirmed thesis, small enough to 10x."
  L2  Basket NEW-MEMBERSHIP events: every run archives a timestamped
      snapshot per theme (data/theme_history/<theme>/); names newly
      entering a basket since the previous snapshot = institutional
      thesis forming NOW. The 2025-26 quantum 10x names all entered
      QTUM long before they 10x'd.
  L3  SEC full-text search keyword discovery: companies whose recent
      filings mention theme keywords but are NOT in any ETF basket —
      the earliest (and dirtiest) layer, pre-institutional.

Output: data/venture_universe.csv + outputs/venture_universe_report.md

Usage:
    .venv/bin/python scripts/build_venture_universe.py [--fts] [--window-min 1e8 --window-max 3e9]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.scanner import (  # noqa: E402
    NetworkMonitor,
    SHARES_TAGS,
    QUARTERLY_FORMS,
    load_config,
    pick_latest_and_year_ago_with_forms,
    price_from_snapshot,
    reconcile_share_unit_scale,
    write_csv_atomic,
)
from ai_value_scanner.backtest import load_alpaca_client, load_sec_client  # noqa: E402

THEMES = ["nuclear", "quantum", "biotech", "rare_earth", "critical_minerals"]


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[venture {stamp}] {msg}", flush=True)


def sec_fts_search(sec_client, query: str, startdt: str, forms: str = "8-K,10-Q,10-K") -> list[str]:
    """SEC full-text search -> CIKs (zfill 10). Degrades to [] on any error."""
    url = (
        f"https://efts.sec.gov/LATEST/search-index?q={query}"
        f"&forms={forms}&startdt={startdt}"
    )
    try:
        resp = sec_client._get(url)
        if resp.status_code != 200:
            log(f"FTS {query!r}: HTTP {resp.status_code}")
            return []
        data = resp.json()
        ciks: list[str] = []
        for hit in (data.get("hits", {}).get("hits", {}) or {}).values() if isinstance(
            data.get("hits", {}).get("hits"), dict
        ) else data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            for cik in src.get("ciks", []):
                ciks.append(str(cik).zfill(10))
        return sorted(set(ciks))
    except Exception as exc:
        log(f"FTS {query!r}: {type(exc).__name__}: {exc}")
        return []


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="configs/theme_universe.json")
    p.add_argument("--window-min", type=float, default=1e8)
    p.add_argument("--window-max", type=float, default=3e9)
    p.add_argument("--min-dollar-volume", type=float, default=5e5)
    p.add_argument("--fts", action="store_true", help="Enable L3 SEC full-text search discovery")
    p.add_argument("--fts-lookback-days", type=int, default=90)
    args = p.parse_args()

    cfg = load_config("configs/config.risk_off.json")
    registry = json.loads(Path(args.registry).read_text())["themes"]
    monitor = NetworkMonitor()
    sec = load_sec_client(cfg, monitor)
    mapping = sec.ticker_mapping()
    client, _ = load_alpaca_client(cfg)

    # ---------- L1: theme baskets -> venture window ----------
    rows: list[dict] = []
    all_syms: set[str] = set()
    theme_of: dict[str, list[str]] = {}
    for theme in THEMES:
        path = Path(f"data/theme_watchlist_{theme}.csv")
        if not path.exists():
            log(f"L1: {theme} 篮子缺失，跳过（先跑 build_theme_universe.py）")
            continue
        d = pd.read_csv(path)
        for _, r in d.iterrows():
            sym = str(r["symbol"]).upper()
            all_syms.add(sym)
            theme_of.setdefault(sym, []).append(theme)
    log(f"L1: 全部主题篮子合计 {len(all_syms)} 只标的")

    syms = sorted(all_syms)
    snaps = client.get_snapshots(syms, cfg.chunk_size) if syms else {}
    px = {s: price_from_snapshot(snaps.get(s, {})) for s in syms}

    venture_rows: list[dict] = []
    for s in syms:
        price, dvol = px[s]
        if price is None:
            continue
        row = mapping[mapping["symbol"] == s]
        if row.empty:
            continue
        cik = row.iloc[0]["cik"]
        try:
            facts = sec.get_companyfacts(cik)
        except Exception:
            continue
        if not facts:
            continue
        shares, _ = pick_latest_and_year_ago_with_forms(facts, SHARES_TAGS, "shares", QUARTERLY_FORMS)
        shares, _scale_flag = reconcile_share_unit_scale(facts, shares)
        if shares is None or shares <= 0:
            continue
        mcap = shares * price
        in_window = args.window_min <= mcap <= args.window_max
        liq_ok = (dvol or 0) >= args.min_dollar_volume
        venture_rows.append({
            "symbol": s,
            "themes": ",".join(theme_of[s]),
            "price": round(price, 2),
            "market_cap": round(mcap),
            "dollar_volume": round(dvol or 0),
            "in_window": bool(in_window and liq_ok),
        })
    l1 = pd.DataFrame(venture_rows)
    l1_venture = l1[l1["in_window"] == True].copy()  # noqa: E712
    log(f"L1: 市值窗 ${args.window_min/1e9:.1f}B-${args.window_max/1e9:.1f}B + 流动性 ≥${args.min_dollar_volume/1e3:.0f}k → {len(l1_venture)} 只")

    # ---------- L2: basket new-membership events ----------
    # Microsecond resolution: two runs within the same second must not share
    # a snapshot filename (that would make snaps_[-2]==snaps_[-1] and silently
    # drop the new-membership diff).
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    new_members: dict[str, list[str]] = {}
    for theme in THEMES:
        src = Path(f"data/theme_watchlist_{theme}.csv")
        if not src.exists():
            continue
        hist_dir = Path(f"data/theme_history/{theme}")
        hist_dir.mkdir(parents=True, exist_ok=True)
        dest = hist_dir / f"{now_stamp}.csv"
        dest.write_text(src.read_text())
        snaps_ = sorted(hist_dir.glob("*.csv"))
        if len(snaps_) >= 2:
            prev = pd.read_csv(snaps_[-2])
            cur = pd.read_csv(snaps_[-1])
            added = sorted(set(cur["symbol"].astype(str).str.upper()) - set(prev["symbol"].astype(str).str.upper()))
            removed = sorted(set(prev["symbol"].astype(str).str.upper()) - set(cur["symbol"].astype(str).str.upper()))
            if added:
                new_members[theme] = added
            log(f"L2 {theme}: 快照 #{len(snaps_)} | 新进 {added} | 移出 {removed}")
        else:
            log(f"L2 {theme}: 首个快照 #{len(snaps_)}（下轮起可 diff）")

    # ---------- L3: SEC full-text search keyword discovery ----------
    l3_syms: dict[str, list[str]] = {}
    if args.fts:
        startdt = (datetime.now(timezone.utc) - pd.Timedelta(days=args.fts_lookback_days)).strftime("%Y-%m-%d")
        for theme, spec in registry.items():
            kws = spec.get("disclosure_keywords", [])[:3]  # top-3 signal keywords per theme
            found: set[str] = set()
            for kw in kws:
                q = f'%22{kw.replace(" ", "+")}%22'
                ciks = sec_fts_search(sec, q, startdt)
                for cik in ciks:
                    m = mapping[mapping["cik"] == cik]
                    if not m.empty:
                        found.add(m.iloc[0]["symbol"])
            fresh = sorted(found - all_syms)
            if fresh:
                l3_syms[theme] = fresh
            log(f"L3 {theme}: FTS 关键词 → {len(found)} 家，其中 {len(fresh)} 家不在任何 ETF 篮子")
    else:
        log("L3: 跳过（--fts 启用 SEC 全文检索发现层）")

    # ---------- 输出 ----------
    out = l1_venture if not l1_venture.empty else l1.head(0)
    out = out.copy()
    out["is_new_member"] = out["symbol"].map(
        lambda s: any(s in v for v in new_members.values())
    )
    if out.empty:
        log("WARNING: L1 产出为空（上游抓取可能失败），保留旧 universe 不覆盖")
    else:
        write_csv_atomic(out, "data/venture_universe.csv")

    # ---------- 每主题 venture watchlist（L1 篮子 + L3 FTS 名单合并）----------
    # Venture 扫描配置 (configs/config.venture.<theme>.json) 的输入。
    # L3 名单 etf_count=0、etfs=SRC:SEC_FTS（来源标签不计入 ETF 计数）。
    now_iso = datetime.now(timezone.utc).isoformat()
    for theme in THEMES:
        src = Path(f"data/theme_watchlist_{theme}.csv")
        if not src.exists():
            continue
        basket = pd.read_csv(src)
        basket["symbol"] = basket["symbol"].astype(str).str.upper()
        extra_syms = set(l3_syms.get(theme, []))
        have = set(basket["symbol"])
        l3_rows = pd.DataFrame([
            {"symbol": s, "bucket": theme, "etf_count": 0,
             "etfs": "SRC:SEC_FTS", "enabled": 1, "updated_utc": now_iso}
            for s in sorted(extra_syms - have)
        ])
        merged = pd.concat([basket, l3_rows], ignore_index=True) if not l3_rows.empty else basket
        merged = merged.drop_duplicates(subset=["symbol"], keep="first")
        vpath = Path(f"data/venture_watchlist_{theme}.csv")
        if merged.empty:
            log(f"WARNING: {theme} 合并结果为空，保留旧 watchlist 不覆盖")
            continue
        write_csv_atomic(merged, vpath)
        log(f"venture watchlist {theme}: {len(merged)} 只（篮子 {len(basket)} + L3 新增 {len(merged)-len(basket)}）→ {vpath}")

    report = [
        f"# Venture Sleeve Universe — {now_stamp}",
        "",
        f"- L1 主题篮子合计: {len(all_syms)} 只 → 市值窗+流动性过滤后: **{len(l1_venture)} 只**",
        f"- L2 篮子新成员事件: {json.dumps(new_members, ensure_ascii=False) if new_members else '本轮无（首快照或无变化）'}",
        f"- L3 SEC 全文检索发现（不在任何 ETF 篮子）: " + (
            json.dumps(l3_syms, ensure_ascii=False) if l3_syms else "未启用/无"
        ),
        "",
        "## L1 venture 窗口标的（按市值降序，前 40）",
        "",
        "| symbol | themes | price | market_cap | dollar_volume | 新成员 |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in out.sort_values("market_cap", ascending=False).head(40).iterrows():
        report.append(
            f"| {r['symbol']} | {r['themes']} | {r['price']} | {r['market_cap']/1e6:,.0f}M | "
            f"{r['dollar_volume']/1e3:,.0f}k | {'是' if r['is_new_member'] else ''} |"
        )
    Path("outputs/venture_universe_report.md").write_text("\n".join(report))
    log(f"输出: data/venture_universe.csv ({len(out)} 只) + outputs/venture_universe_report.md")


if __name__ == "__main__":
    main()
