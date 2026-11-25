# 报告阅读目录

在浏览器打开 `index.html`，从最近一期的日报或周报进入个股详报，也可以选择首页上的历史交易日。首页显示最近成功导出的交易日。

```text
reports/
  index.html
  history/
    YYYY-MM-DD/
      daily.html
      weekly.html
      detailed/<股票代码>.html
      short_candidates.csv       # 当期报告链接到该文件时
```

页面是经校验的正式生产 SIP 快照的离线阅读副本。复制整个 `reports/` 目录即可保留页面之间的相对链接。正式快照和来源信息在 [decisions/](../decisions/README.md)。

正式生产批处理成功时自动更新最新一期。首次需要补齐已有历史阅读页时，在项目根目录运行 `python scripts/export_reading_reports.py --include-history`。省略 `--include-history` 可重新导出最新一期。异常排查和安装方式见[使用手册](../../docs/swing_trading_user_guide.md)。
