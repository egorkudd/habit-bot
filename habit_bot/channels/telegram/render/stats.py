"""Картинки и текст статистики (раздел 3.8): Pillow по готовым данным, без ИИ и без файлов на диске —
картинка собирается в памяти и сразу уходит в Telegram."""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from decimal import Decimal
from functools import cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from habit_bot.kernel.domain.formatting import format_number
from habit_bot.platform.stats.data import Bar, DayStats, Overview, Table
from habit_bot.platform.stats.domain.traffic import ICON, LEGEND, Color, percent

FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")
# Три оттенка (правка 1.0.1): выполнено — чёрная, частично — серая, ничего — белая с рамкой.
COLORS = {Color.DONE: (33, 37, 41), Color.PARTIAL: (160, 166, 173), Color.NONE: (255, 255, 255),
          Color.OFF: (228, 232, 236), Color.SKIP: (246, 247, 248), Color.FUTURE: (255, 255, 255)}
OUTLINE = {Color.NONE: (150, 156, 163), Color.FUTURE: (236, 238, 240)}
INK, MUTED, LINE, PAPER, TRACK = (33, 37, 41), (110, 117, 125), (222, 226, 230), (255, 255, 255), (236, 238, 240)
WIDTH, PAD = 760, 28
BAR_CHARS = 12
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
PARTS = " ▏▎▍▌▋▊▉"


@cache
def font(size: int, bold: bool = False) -> Any:
    """DejaVu Sans (кириллица, ▲▼, ★); если шрифта нет — встроенный Pillow, чтобы картинка всё равно была."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for folder in FONT_DIRS:
        try:
            return ImageFont.truetype(f"{folder}/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default(size)  # pragma: no cover — в образе и в CI DejaVu установлен


def plain(text: str) -> str:
    """Эмодзи шрифт не рисует: 🏆 → ★, остальные убираются."""
    text = text.replace("🏆", "★")
    return "".join(ch for ch in text if ord(ch) < 0x1F000 and ch not in "️‍").strip()


# Телефонный Telegram показывает в чате слишком широкую (или узкую) картинку обрезанной по краям — целиком она
# видна, только если её открыть (правки 1.0.2). Поэтому картинка дополняется полями до пропорций не шире 3:2
# и не уже 1:2, содержимое — по центру.
MAX_RATIO, MIN_RATIO = 1.5, 0.5


def fit_ratio(image: Image.Image) -> Image.Image:
    width, height = image.size
    target = (width, max(height, round(width / MAX_RATIO)))
    target = (max(target[0], round(target[1] * MIN_RATIO)), target[1])
    if target == image.size:
        return image
    framed = Image.new("RGB", target, PAPER)
    framed.paste(image, ((target[0] - width) // 2, (target[1] - height) // 2))
    return framed


def _png(image: Image.Image) -> bytes:
    image = fit_ratio(image)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _width(draw: ImageDraw.ImageDraw, text: str, size: int, bold: bool = False) -> int:
    return int(draw.textlength(text, font=font(size, bold)))


def _amount(value: Decimal) -> str:
    return format_number(value.quantize(Decimal(1)) if value >= 100 else value)


# --- картинка дня ---
def _table_widths(draw: ImageDraw.ImageDraw, table: Table) -> list[int]:
    widths = []
    for i, header in enumerate(table.headers):
        cells = [header, *(row[i] for row in table.rows)]
        widths.append(max(_width(draw, plain(c), 20, bold=c is header) for c in cells) + 18)
    extra = WIDTH - 2 * PAD - sum(widths)
    if extra > 0:
        widths[0] += extra
    return widths


def _wrap(draw: ImageDraw.ImageDraw, text: str, size: int, width: int) -> list[str]:
    """Перенос по словам, чтобы длинная строка (прогресс личной цели) не обрезалась справа."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if current and _width(draw, candidate, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return [*lines, current]


def day_png(data: DayStats) -> bytes:
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = [part for line in data.lines for part in _wrap(probe, plain(line), 20, WIDTH - 2 * PAD)]
    height = PAD + 44 + 54 * len(data.bars) + 30 * len(lines) + PAD + (10 if lines else 0)
    for table in data.tables:
        height += 16 + 34 * (len(table.rows) + 1)
    if data.empty:
        height += 30
    image = Image.new("RGB", (WIDTH, max(height, 140)), PAPER)
    draw = ImageDraw.Draw(image)
    y = PAD
    draw.text((PAD, y), plain(data.title), font=font(28, True), fill=INK)
    y += 48
    # подписи полос — колонкой по самой длинной («Витамины» не залезает на полосу), полоса укорачивается
    label_w = max([110, *(_width(probe, plain(b.label), 20, True) + 16 for b in data.bars)])
    label_w = min(label_w, 260)
    for bar in data.bars:
        _bar(draw, bar, y, PAD + label_w, 300 - max(0, label_w - 110))
        y += 54
    for table in data.tables:
        y += 12
        y = _table(draw, probe, table, y)
    if data.empty:
        draw.text((PAD, y), "Записей нет", font=font(20), fill=MUTED)
        y += 30
    y += 10 if lines else 0
    for line in lines:
        draw.text((PAD, y), line, font=font(20), fill=INK)
        y += 30
    return _png(image)


def _bar(draw: ImageDraw.ImageDraw, bar: Bar, y: int, left: int, track: int) -> None:
    draw.text((PAD, y + 6), plain(bar.label), font=font(20, True), fill=INK)
    draw.rounded_rectangle((left, y + 4, left + track, y + 34), radius=8, fill=TRACK)
    share = percent(bar.fact, bar.goal)
    if share:
        filled = int(track * min(share, 100) / 100)
        if filled > 0:
            draw.rounded_rectangle((left, y + 4, left + max(filled, 16), y + 34), radius=8, fill=COLORS[bar.color])
    shown = f"{share}%" if share is not None else ""
    goal = f" / {_amount(bar.goal)}" if bar.goal else ""
    draw.text((left + track + 14, y + 6), f"{shown}  {_amount(bar.fact)}{goal}{(' ' + bar.unit) if bar.unit else ''}",
              font=font(20), fill=INK)


def _table(draw: ImageDraw.ImageDraw, probe: ImageDraw.ImageDraw, table: Table, y: int) -> int:
    widths = _table_widths(probe, table)
    for r, row in enumerate([table.headers, *table.rows]):
        x = PAD
        for i, cell in enumerate(row):
            text = plain(cell)
            bold = r == 0
            fill = MUTED if bold else INK
            if i in table.right:
                draw.text((x + widths[i] - 12 - _width(draw, text, 20, bold), y + 4), text, font=font(20, bold),
                          fill=fill)
            else:
                draw.text((x + 4, y + 4), text, font=font(20, bold), fill=fill)
            x += widths[i]
        y += 34
        draw.line((PAD, y - 2, WIDTH - PAD, y - 2), fill=LINE, width=1)
    return y


# --- обзор-светофор ---
def overview_png(data: Overview) -> bytes:
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    count = len(data.days)
    cell = max(10, min(46, 720 // max(count, 1)))
    gap = 3 if cell >= 16 else 1
    label_w = max([_width(probe, plain(r.label), 20) for r in data.rows] + [120]) + 16
    grid_w = count * (cell + gap)
    width = PAD + label_w + grid_w + 150 + PAD
    row_h = max(cell, 26) + 8
    height = PAD + 44 + 30 + row_h * max(len(data.rows), 1) + 40 + PAD
    image = Image.new("RGB", (max(width, 600), height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((PAD, PAD), plain(data.title), font=font(28, True), fill=INK)
    top = PAD + 48
    left = PAD + label_w
    step = 1 if cell >= 24 else 7
    for i, day in enumerate(data.days):
        if i % step == 0:
            label = f"{WEEKDAYS[day.weekday()]} {day.day}" if cell >= 40 else f"{day.day}"
            bold = day == data.today
            draw.text((left + i * (cell + gap), top), label, font=font(14, bold), fill=INK if bold else MUTED)
    draw.text((left + grid_w + 16, top), "выполнено · серия", font=font(14), fill=MUTED)
    y = top + 26
    if not data.rows:
        draw.text((PAD, y + 4), "За этот период записей нет", font=font(20), fill=MUTED)
    for row in data.rows:
        draw.text((PAD, y + (row_h - 30) // 2 + 2), plain(row.label), font=font(20), fill=INK)
        for i, color in enumerate(row.cells):
            x0 = left + i * (cell + gap)
            y0 = y + (row_h - 8 - cell) // 2
            box = (x0, y0, x0 + cell, y0 + cell)
            _cell(draw, box, color, cell)
        share = f"{row.green}%" if row.green is not None else "—"
        draw.text((left + grid_w + 16, y + (row_h - 30) // 2 + 2), f"{share} · {row.streak}", font=font(20),
                  fill=INK)
        y += row_h
    if data.today in data.days and data.rows:  # сегодняшний день — в рамке, чтобы прогресс дня было видно сразу
        i = data.days.index(data.today)
        x0 = left + i * (cell + gap) - 2
        draw.rounded_rectangle((x0, top + 22, x0 + cell + 4, y - 2), radius=4, outline=INK, width=2)
    x = PAD
    for color, text in ((Color.DONE, "выполнено"), (Color.PARTIAL, "частично"), (Color.NONE, "ничего"),
                        (Color.OFF, "выходной")):
        _cell(draw, (x, height - PAD - 20, x + 16, height - PAD - 4), color, 16)
        draw.text((x + 22, height - PAD - 22), text, font=font(16), fill=MUTED)
        x += 22 + _width(draw, text, 16) + 18
    return _png(image)


def _cell(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: Color, size: int) -> None:
    draw.rounded_rectangle(box, radius=3, fill=COLORS[color], outline=OUTLINE.get(color),
                           width=1 if color in OUTLINE else 0)
    if color is Color.OFF and size >= 14:
        letter = int(size * 0.6)
        w = _width(draw, "в", letter)
        draw.text((box[0] + (size - w) / 2, box[1] + size * 0.12), "в", font=font(letter), fill=MUTED)


# --- «Текстом»: та же таблица моноширинным блоком ---
def text_bar(bar: Bar) -> str:
    share = percent(bar.fact, bar.goal)
    filled = Decimal(min(share or 0, 100)) * BAR_CHARS / 100
    whole = int(filled)
    part = PARTS[int((filled - whole) * 8)] if whole < BAR_CHARS else ""
    track = ("█" * whole + part.strip()).ljust(BAR_CHARS, "░")
    goal = f" / {_amount(bar.goal)}" if bar.goal else ""
    shown = f"{share}%" if share is not None else "—"
    return f"{bar.label:<6} {track} {shown:>4}  {_amount(bar.fact)}{goal}  {ICON[bar.color]}"


def text_table(table: Table) -> list[str]:
    rows = [table.headers, *table.rows]
    widths = [max(len(r[i]) for r in rows) for i in range(len(table.headers))]
    out = []
    for row in rows:
        out.append("  ".join(c.rjust(widths[i]) if i in table.right else c.ljust(widths[i])
                             for i, c in enumerate(row)).rstrip())
    return out


def day_text(data: DayStats) -> str:
    lines = [data.title]
    lines += [text_bar(b) for b in data.bars]
    for table in data.tables:
        lines += ["", *text_table(table)]
    if data.empty:
        lines.append("Записей нет")
    if data.lines:
        lines += ["", *data.lines]
    return "\n".join(lines)


def _weeks(cells: Sequence[Color]) -> Iterable[str]:
    for start in range(0, len(cells), 7):
        yield "".join(ICON[c] for c in cells[start:start + 7])


def overview_text(data: Overview) -> str:
    lines = [data.title]
    if not data.rows:
        return "\n".join([*lines, "За этот период записей нет"])
    width = max(len(r.label) for r in data.rows)
    for row in data.rows:
        share = f"{row.green}%" if row.green is not None else "—"
        summary = f"{share} · серия {row.streak}"
        if len(data.days) > 31:
            lines.append(f"{row.label:<{width}}  {summary}")
            continue
        weeks = list(_weeks(row.cells))
        lines.append(f"{row.label:<{width}}  {weeks[0]}  {summary}" if len(weeks) == 1
                     else f"{row.label}  {summary}")
        if len(weeks) > 1:
            lines += [f"  {w}" for w in weeks]
    lines += ["", LEGEND]
    return "\n".join(lines)
