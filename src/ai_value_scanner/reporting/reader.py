"""Publish a portable, offline reading copy of validated production SIP reports."""
from __future__ import annotations

import fcntl
from html import escape
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .publication import read_latest_publication, validate_publication_reports
from .snapshot import load_snapshot_decisions, load_snapshot_manifest


_TAGS = set("p h1 h2 h3 h4 h5 h6 ul ol li table thead tbody tr th td b strong em code pre "
            "blockquote br hr a details summary".split())
_MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_STYLE = """
*{box-sizing:border-box}body{margin:0 auto;padding:1.25rem;max-width:72rem;color:#21313d;
background:#fafbf9;font:1rem/1.65 "Source Sans 3","Noto Sans CJK SC",system-ui,sans-serif}nav{display:flex;gap:1.3rem;
flex-wrap:wrap;border-bottom:1px solid #bdc9c7;padding:.5rem 0}a{color:#075955}
h1,h2,h3{line-height:1.3}h2{margin-top:2rem}details{background:white;padding:.65rem 1rem;
border:1px solid #d5ddda;margin:.55rem 0}summary{cursor:pointer}
table{display:block;overflow:auto;border-collapse:collapse}th,td{padding:.3rem .65rem;
border:1px solid #c8d3d0;text-align:left}code{overflow-wrap:anywhere}li{margin:.24rem 0}
.latest{padding:1.2rem 1.5rem;background:#edf4ee;border-left:4px solid #24685b}
.latest h2{margin:0}.latest a{display:inline-block;padding:.45rem 1rem;margin:.1rem .4rem .1rem 0;
background:#215a50;color:white;border-radius:.3rem}.archive{padding-left:1.25rem}
"""


def _page(title: str, nav: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{_STYLE}</style></head><body>{nav}<main>{body}</main></body></html>
"""


def _body(markdown: str, links: dict[str, str], used_links: set[str]) -> str:
    # The reports mix Markdown with HTML disclosure lists. Preserve these and
    # their jump anchors without carrying active content into local HTML files.
    document = BeautifulSoup(_MARKDOWN.render(markdown), "html.parser")
    for element in document.find_all(["script", "style"]):
        element.decompose()
    anchors = {tag["id"] for tag in document.find_all("a", id=True)}
    for tag in document.find_all(True):
        if tag.name not in _TAGS:
            tag.unwrap()
            continue
        attrs = tag.attrs
        tag.attrs = {}
        if tag.name == "details" and "open" in attrs:
            tag["open"] = ""
        if tag.name != "a":
            continue
        if anchor := attrs.get("id"):
            tag["id"] = anchor
        href = attrs.get("href", "")
        path, sep, fragment = href.partition("#")
        if path.startswith("./"):
            path = path[2:]
        if path in links:
            tag["href"] = links[path] + sep + fragment
            used_links.add(path)
        elif not path and sep and fragment in anchors:
            tag["href"] = href
        elif href.startswith(("https://", "http://")):
            tag["href"] = href
        elif not tag.attrs:
            # Some archive revisions list section jumps even on days when the
            # section has no members. Keep the label as plain text.
            tag.unwrap()
    return str(document)


def _export_day(snapshot: Path, manifest: dict, history: Path) -> None:
    day = snapshot.parent.name
    daily = (snapshot / "action_list.md").read_text(encoding="utf-8")
    weekly = (snapshot / "weekly_review.md").read_text(encoding="utf-8")
    # Only ship evidence linked by the validated lists. Extra files in an
    # archive can be local operator notes unrelated to the publication.
    symbols = {item.symbol for item in load_snapshot_decisions(snapshot)}
    links = {f"detailed/{s}.md": f"detailed/{s}.html" for s in symbols if Path(s).name == s}
    used_links: set[str] = set()
    destination = history / day
    with TemporaryDirectory(dir=history, prefix=".render-") as temp:
        stage = Path(temp) / day
        (stage / "detailed").mkdir(parents=True)
        if manifest.get("short_research") and (snapshot / "short_candidates.csv").is_file():
            links["short_candidates.csv"] = "short_candidates.csv"

        def save(path: Path, title: str, source: str, mapping: dict[str, str], prefix: str) -> None:
            nav = (f'<nav><a href="{prefix}../../index.html">报告首页</a>'
                   f'<a href="{prefix}daily.html">日报</a><a href="{prefix}weekly.html">周报</a>'
                   f'<span>正式 SIP · {day}</span></nav>')
            path.write_text(_page(f"{day} · {title}", nav, _body(source, mapping, used_links)), encoding="utf-8")

        save(stage / "daily.html", "日报", daily, links, "")
        save(stage / "weekly.html", "周报", weekly, links, "")
        if "short_candidates.csv" in used_links:
            (stage / "short_candidates.csv").write_bytes((snapshot / "short_candidates.csv").read_bytes())
        for rel in sorted(used_links):
            if not rel.startswith("detailed/"):
                continue
            source = (snapshot / rel).read_text(encoding="utf-8")
            save(stage / links[rel], Path(rel).stem, source,
                 {"../action_list.md": "../daily.html", "../weekly_review.md": "../weekly.html"}, "../")

        if not destination.exists():
            stage.rename(destination)
        else:
            # A retry (or an updated presentation) replaces only complete files
            # for the same immutable session, after all rendering has succeeded.
            (destination / "detailed").mkdir(exist_ok=True)
            for file in stage.rglob("*"):
                if file.is_file():
                    os.replace(file, destination / file.relative_to(stage))


def _index(output: Path, day: str) -> Path:
    def links(token: str) -> str:
        return (f'<a href="history/{token}/daily.html">日报</a> · '
                f'<a href="history/{token}/weekly.html">周报</a>')

    rows = []
    for folder in sorted((output / "history").iterdir(), reverse=True):
        if (_DAY.fullmatch(folder.name) and folder.name < day
                and all((folder / name).is_file() for name in ("daily.html", "weekly.html"))):
            rows.append(f"<li>{folder.name}　{links(folder.name)}</li>")
    body = (f'<h1>选股报告</h1><section class="latest"><h2>最近发布 · {day}</h2>'
            f'<p>正式 SIP 收盘报告 · 美股交易日</p>'
            f'<a href="history/{day}/daily.html">阅读日报</a>'
            f'<a href="history/{day}/weekly.html">阅读周报</a></section>')
    if rows:
        body += '<h2>历史报告</h2><ul class="archive">' + "".join(rows) + "</ul>"
    path = output / "index.html"
    with TemporaryDirectory(dir=output, prefix=".index-") as tmpdir:
        temp = Path(tmpdir) / "index.html"
        temp.write_text(_page(f"选股报告 · {day}", "", body), encoding="utf-8")
        os.replace(temp, path)
    return path


def export_reading_reports(snapshot_root: Path, *, include_history: bool = False) -> Path:
    root = snapshot_root.resolve()
    output = (root.parent if root.name == "decisions" else root) / "reports"
    history = output / "history"
    with (root / ".latest_production.lock").open("a") as lock:
        # Share the writer's lock so a retry cannot install yesterday's index
        # after a newer publication. Select the pointer again under the lock.
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        latest = read_latest_publication(root, "production")
        day = latest["decision_date"]
        history.mkdir(parents=True, exist_ok=True)
        if include_history:
            for folder in sorted(root.iterdir()):
                if not _DAY.fullmatch(folder.name) or folder.name >= day:
                    continue
                archive = folder / "production"
                if not (archive / "run_manifest.json").is_file():
                    continue
                manifest = load_snapshot_manifest(archive)
                provenance = manifest.get("input_provenance") or {}
                if provenance.get("market_data_mode") != "sip_eod":
                    continue
                if manifest["decision_date"] != folder.name or manifest["strategy_style"] != "production":
                    raise ValueError(f"Archive identity mismatch in {archive}")
                validate_publication_reports(archive, manifest, require_sip=True)
                _export_day(archive, manifest, history)
        current = root / latest["snapshot_dir"]
        _export_day(current, load_snapshot_manifest(current), history)
        return _index(output, day)
