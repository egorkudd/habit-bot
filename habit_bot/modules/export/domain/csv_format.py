"""Экспорт CSV (раздел 3.12): удобно и нейросети, и Excel.

UTF-8 с BOM, разделитель — запятая, десятичная точка, даты ГГГГ-ММ-ДД, время ЧЧ:ММ, одна строка — одна запись,
заголовки на английском в snake_case, без итоговых строк. ``README.csv`` — словарь колонок."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum

BOM = "﻿"
Cell = str | int | float | Decimal | date | time | datetime | bool | Enum | None


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    description: str
    unit: str = ""


@dataclass(frozen=True, slots=True)
class TableSpec:
    key: str
    filename: str
    title: str  # подпись галочки в боте
    row: str    # что такое одна строка — для README
    columns: tuple[Column, ...]


def cell(value: Cell) -> str:
    """Значение для CSV: десятичная точка без лишних нулей, ISO-дата, ЧЧ:ММ, пусто вместо «нет»."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (Decimal, float)):
        number = Decimal(str(value)).quantize(Decimal("0.01")).normalize()
        text = f"{number:f}"
        return "0" if text in ("-0", "0") else text
    return str(value)


def to_csv(spec: TableSpec, rows: Iterable[Sequence[Cell]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([c.name for c in spec.columns])
    for row in rows:
        if len(row) != len(spec.columns):
            raise ValueError(f"{spec.filename}: в строке {len(row)} значений, а колонок {len(spec.columns)}")
        writer.writerow([cell(v) for v in row])
    return (BOM + buffer.getvalue()).encode("utf-8")


README = TableSpec("readme", "README.csv", "Словарь колонок", "одна колонка одного файла", (
    Column("file", "имя файла"), Column("column", "колонка"), Column("description", "что в ней"),
    Column("unit", "единица измерения"),
))


def readme(specs: Sequence[TableSpec]) -> bytes:
    rows: list[Sequence[Cell]] = []
    for spec in specs:
        rows.append((spec.filename, "", f"одна строка — {spec.row}", ""))
        rows += [(spec.filename, c.name, c.description, c.unit) for c in spec.columns]
    return to_csv(README, rows)
