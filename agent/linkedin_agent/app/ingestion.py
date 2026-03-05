from __future__ import annotations

import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import yaml

from .audit import log_event
from .compliance import assert_no_pii
from .db import connect, utc_now
from .models import SourceItem


def _stable_id(prefix: str, raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _insert_source(db_path: Path, item: SourceItem) -> bool:
    with connect(db_path) as conn:
        existing = conn.execute("SELECT id FROM ingestions WHERE source_id = ?", (item.source_id,)).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO ingestions (source_type, source_id, title, content, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item.source_type, item.source_id, item.title, item.content, item.source_ref, utc_now()),
        )
    return True


def scan_experiments(experiments_dir: Path) -> list[SourceItem]:
    items: list[SourceItem] = []
    for path in sorted(experiments_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        title = str(payload.get("title") or path.stem)
        summary = str(payload.get("summary") or payload.get("description") or "")
        image_refs = payload.get("images") or []
        content = f"{summary}\nImages: {', '.join(map(str, image_refs))}".strip()
        assert_no_pii(content)
        source_ref = str(path)
        items.append(
            SourceItem(
                source_type="experiment",
                source_id=_stable_id("exp", source_ref + content),
                title=title,
                content=content,
                source_ref=source_ref,
            )
        )
    return items


def scan_notes(notes_dir: Path) -> list[SourceItem]:
    items: list[SourceItem] = []
    for path in sorted(notes_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        assert_no_pii(content)
        lines = [line.strip("# ") for line in content.splitlines() if line.strip()]
        title = lines[0] if lines else path.stem
        items.append(
            SourceItem(
                source_type="note",
                source_id=_stable_id("note", str(path) + content[:200]),
                title=title,
                content=content,
                source_ref=str(path),
            )
        )
    return items


def _parse_rss(xml_text: str, feed_name: str) -> Iterable[SourceItem]:
    root = ET.fromstring(xml_text)
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        content = f"{title}\n{description}".strip()
        assert_no_pii(content)
        yield SourceItem(
            source_type="feed",
            source_id=_stable_id("feed", f"{feed_name}:{link}:{title}"),
            title=title,
            content=description,
            source_ref=link or f"rss:{feed_name}",
        )


def poll_rss(feeds_config: Path, feed_cache_dir: Path, timeout: int = 8) -> list[SourceItem]:
    feed_cache_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(feeds_config.read_text(encoding="utf-8")) or {}
    items: list[SourceItem] = []
    for feed in cfg.get("feeds", []):
        if not feed.get("enabled", False):
            continue
        name = str(feed.get("name") or "feed")
        url = str(feed.get("url") or "").strip()
        if not url:
            continue
        with urllib.request.urlopen(url, timeout=timeout) as response:  # nosec B310
            body = response.read().decode("utf-8", errors="ignore")
        (feed_cache_dir / f"{name}.xml").write_text(body, encoding="utf-8")
        items.extend(list(_parse_rss(body, name)))
    return items


def ingest_all(db_path: Path, experiments_dir: Path, notes_dir: Path, feeds_config: Path, feed_cache_dir: Path) -> dict[str, int]:
    gathered = [
        *scan_experiments(experiments_dir),
        *scan_notes(notes_dir),
        *poll_rss(feeds_config, feed_cache_dir),
    ]
    inserted = 0
    for item in gathered:
        if _insert_source(db_path, item):
            inserted += 1
            log_event(
                db_path,
                event_type="ingested",
                entity_type="source",
                entity_id=item.source_id,
                payload={"source_type": item.source_type, "source_ref": item.source_ref},
            )
    return {"scanned": len(gathered), "inserted": inserted}
