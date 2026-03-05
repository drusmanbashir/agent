from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

WEEKDAY_OFFSET = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
}


@dataclass(frozen=True)
class MdtMeeting:
    meeting_name: str
    date_iso: str
    weekday: str
    assignment: str
    month_label: str


def _cell_text(cell: ET.Element) -> str:
    chunks: list[str] = []
    for p in cell.findall(".//text:p", NS):
        text = "".join(p.itertext()).strip()
        if text:
            chunks.append(text)
    return " ".join(chunks).strip()


def _load_sheet_grid(ods_path: Path) -> list[list[str]]:
    with zipfile.ZipFile(ods_path) as zf:
        root = ET.fromstring(zf.read("content.xml"))

    table = root.find(".//table:table", NS)
    if table is None:
        raise ValueError(f"No table found in {ods_path}")

    grid: list[list[str]] = []
    for row in table.findall("table:table-row", NS):
        row_repeat = int(row.attrib.get(f"{{{NS['table']}}}number-rows-repeated", "1"))
        expanded: list[str] = []
        for cell in row.findall("table:table-cell", NS):
            col_repeat = int(cell.attrib.get(f"{{{NS['table']}}}number-columns-repeated", "1"))
            value = _cell_text(cell)
            expanded.extend([value] * col_repeat)
        for _ in range(row_repeat):
            grid.append(list(expanded))
    return grid


def _contains_initials(value: str, initials: str) -> bool:
    pattern = rf"(^|[^A-Za-z]){re.escape(initials)}([^A-Za-z]|$)"
    return bool(re.search(pattern, value, flags=re.IGNORECASE))


def _month_from_label(value: str) -> int | None:
    key = value.strip().lower()[:4].strip()
    if not key:
        return None
    if key in MONTHS:
        return MONTHS[key]
    key3 = key[:3]
    return MONTHS.get(key3)


def _parse_week_row_label(value: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s*-\s*(\d{1,2})(?:st|nd|rd|th)?", value.lower())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _next_week_bounds(today: date) -> tuple[date, date]:
    days_to_next_monday = 7 - today.weekday()
    monday = today + timedelta(days=days_to_next_monday)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _current_week_bounds(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def extract_mdt_meetings_for_week(
    ods_path: Path,
    initials: str,
    week_mode: str = "next",
    today: date | None = None,
) -> list[MdtMeeting]:
    today = today or date.today()
    if week_mode == "current":
        week_start, week_end = _current_week_bounds(today)
    elif week_mode == "next":
        week_start, week_end = _next_week_bounds(today)
    else:
        raise ValueError("week_mode must be 'current' or 'next'")

    grid = _load_sheet_grid(ods_path)
    if len(grid) < 3:
        return []

    header_row_idx = -1
    for i, row in enumerate(grid[:12]):
        if row and row[0].strip().lower() == "date wk beg":
            header_row_idx = i
            break
    if header_row_idx < 0 or header_row_idx + 1 >= len(grid):
        raise ValueError("Could not find expected header rows in MDT sheet")

    weekday_row = grid[header_row_idx]
    meeting_row = grid[header_row_idx + 1]

    parsed: list[tuple[date, MdtMeeting]] = []
    current_month_label = meeting_row[0].strip() if meeting_row else ""
    current_month_num: int | None = _month_from_label(current_month_label)
    # MDT rota files are short-horizon (about 4 months), so dates are always
    # interpreted in the current calendar year.
    current_year = today.year

    for row in grid[header_row_idx + 2 :]:
        if not row:
            continue
        first_col = row[0].strip() if len(row) > 0 else ""
        if not first_col:
            continue

        month_num = _month_from_label(first_col)
        if month_num is not None:
            current_month_num = month_num
            current_month_label = first_col
            continue

        week_range = _parse_week_row_label(first_col)
        if week_range is None or current_month_num is None:
            continue
        start_day, _ = week_range

        for col_idx in range(1, min(len(row), len(weekday_row), len(meeting_row))):
            assignment = row[col_idx].strip()
            if not assignment or not _contains_initials(assignment, initials):
                continue

            weekday_label = weekday_row[col_idx].strip().lower()
            if weekday_label not in WEEKDAY_OFFSET:
                continue
            day_offset = WEEKDAY_OFFSET[weekday_label]
            meeting_date = date(current_year, current_month_num, start_day) + timedelta(days=day_offset)
            if not (week_start <= meeting_date <= week_end):
                continue

            meeting_name = meeting_row[col_idx].strip() if col_idx < len(meeting_row) else ""
            parsed.append(
                (
                    meeting_date,
                    MdtMeeting(
                        meeting_name=meeting_name or "(Unnamed MDT)",
                        date_iso=meeting_date.isoformat(),
                        weekday=weekday_label.capitalize(),
                        assignment=assignment,
                        month_label=current_month_label,
                    ),
                )
            )

    parsed.sort(key=lambda x: x[0])
    return [m for _, m in parsed]


def extract_next_week_mdt_meetings(
    ods_path: Path,
    initials: str,
    today: date | None = None,
) -> list[MdtMeeting]:
    return extract_mdt_meetings_for_week(
        ods_path=ods_path,
        initials=initials,
        week_mode="next",
        today=today,
    )


def build_friday_notification(meetings: list[MdtMeeting], initials: str, today: date) -> str:
    week_start, week_end = _next_week_bounds(today)
    if not meetings:
        return (
            f"MDT weekly update for {initials}: no MDT assignments found for "
            f"{week_start.isoformat()} to {week_end.isoformat()}."
        )

    lines = [
        f"MDT weekly update for {initials} ({week_start.isoformat()} to {week_end.isoformat()}):",
    ]
    for m in meetings:
        lines.append(f"- {m.date_iso} ({m.weekday}): {m.meeting_name} [{m.assignment}]")
    return "\n".join(lines)


def write_mdt_output(
    out_json: Path,
    meetings: list[MdtMeeting],
    initials: str,
    today: date,
) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "run_at": datetime.utcnow().isoformat() + "Z",
        "initials": initials,
        "today": today.isoformat(),
        "next_week_meetings": [
            {
                "meeting_name": m.meeting_name,
                "date": m.date_iso,
                "weekday": m.weekday,
                "assignment_cell": m.assignment,
                "month_label": m.month_label,
            }
            for m in meetings
        ],
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
