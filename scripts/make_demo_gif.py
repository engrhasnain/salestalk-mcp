"""Render docs/demo.gif from REAL tool calls against the seeded database.

The script starts SalesTalk over stdio (like Claude Desktop does), asks four questions through the
MCP tools, measures each call, and animates the actual results: typed question, tool call, answer.

    uv run --with pillow python scripts/make_demo_gif.py            # needs the database running
    uv run --with pillow python scripts/make_demo_gif.py --out docs/demo.gif
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
# SalesTalk Console palette: lavender section, white window, ink chip, one periwinkle accent.
BG = (245, 244, 251)
WINDOW = (255, 255, 255)
SHADOW = (228, 226, 244)
BORDER = (226, 224, 242)
DIVIDER = (236, 234, 248)
DOT = (226, 224, 242)
INK = (17, 19, 42)
BODY = (59, 62, 94)
MUTED = (95, 98, 136)
FAINT = (139, 142, 176)
BUBBLE = (236, 234, 248)
CHIP = (12, 14, 26)
CHIP_TEXT = (243, 243, 251)
CHIP_FUNC = (142, 152, 255)
CHIP_OK = (47, 211, 154)
CHIP_NO = (242, 85, 90)
ACCENT = (83, 96, 240)
ACCENT_SOFT = (199, 204, 255)
ACCENT_BG = (232, 234, 255)
DANGER = (190, 42, 47)
DANGER_BG = (253, 233, 234)
DANGER_BORDER = (246, 201, 203)

FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
             Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
FONT_FILES = {
    "regular": ["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"],
    "semibold": ["seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    "bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    "mono": ["consola.ttf", "DejaVuSansMono.ttf", "Courier New.ttf"],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONT_FILES[kind]:
        for folder in FONT_DIRS:
            path = folder / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


F_TITLE = font("regular", 15)
F_Q = font("regular", 22)
F_HEAD = font("semibold", 20)
F_ROW = font("regular", 19)
F_ROW_B = font("semibold", 19)
F_MONO = font("mono", 16)
F_MONO_S = font("mono", 14)
F_FOOT = font("regular", 15)


@dataclass
class Row:
    rank: str
    label: str
    sub: str
    value: str
    bar: float  # 0..1


@dataclass
class Scene:
    question: str
    call: str
    elapsed_ms: int
    headline: str
    rows: list[Row] = field(default_factory=list)
    refused: str | None = None


def aed(value: float) -> str:
    return f"{value / 1_000_000:.2f}M" if value >= 1_000_000 else f"{value:,.0f}"


def month_name(ym: str) -> str:
    year, month = (int(p) for p in ym.split("-"))
    return date(year, month, 1).strftime("%B %Y")


async def collect() -> list[Scene]:
    params = StdioServerParameters(command=sys.executable, args=["-m", "salestalk_mcp"], env=dict(os.environ))
    scenes: list[Scene] = []
    async with Client(params) as client:

        async def call(name: str, args: dict[str, Any]) -> tuple[Any, int]:
            start = time.perf_counter()
            result = await client.call_tool(name, args)
            return result, round((time.perf_counter() - start) * 1000)

        res, ms = await call("query_sales", {"month": "last_month", "limit": 5})
        d = res.structured_content
        top = d["top_customers"]
        scenes.append(Scene(
            question="Who were our top 5 customers last month?",
            call='query_sales(month="last_month", limit=5)',
            elapsed_ms=ms,
            headline=(f"{month_name(d['month'])}  ·  AED {aed(d['summary']['revenue'])} from {d['summary']['orders']} "
                      f"orders  ·  {d['previous_period']['revenue_change_pct']:+.1f}% vs previous month"),
            rows=[Row(str(c["rank"]), c["customer"], c["city"], f"AED {c['revenue']:,.0f}",
                      c["revenue"] / top[0]["revenue"]) for c in top],
        ))

        res, ms = await call("revenue_by_city", {"range": "this_quarter"})
        d = res.structured_content
        best = max(c["revenue"] for c in d["cities"])
        scenes.append(Scene(
            question="Compare revenue by city this quarter.",
            call='revenue_by_city(range="this_quarter")',
            elapsed_ms=ms,
            headline=f"This quarter so far  ·  {d['range']['start']} to {d['range']['end']}  ·  revenue in AED",
            rows=[Row("", c["city"], f"{c['orders']} orders", f"AED {c['revenue']:,.0f}", c["revenue"] / best)
                  for c in d["cities"]],
        ))

        res, ms = await call("top_products", {"range": "last_30_days", "limit": 5})
        d = res.structured_content
        prods = d["products"]
        scenes.append(Scene(
            question="What were our best sellers in the last 30 days?",
            call='top_products(range="last_30_days", limit=5)',
            elapsed_ms=ms,
            headline="Last 30 days  ·  ranked by revenue  ·  gross margin in brackets",
            rows=[Row(str(p["rank"]), p["product"], f"{p['units']:,} units  ({p['gross_margin_pct']:.0f}% margin)",
                      f"AED {p['revenue']:,.0f}", p["revenue"] / prods[0]["revenue"]) for p in prods],
        ))

        res, ms = await call("run_sql", {"query": "DELETE FROM orders"})
        text = " ".join(getattr(c, "text", "") for c in res.content).replace("Error executing tool run_sql: ", "")
        scenes.append(Scene(
            question="Delete the orders table.",
            call='run_sql(query="DELETE FROM orders")',
            elapsed_ms=ms,
            headline="",
            refused=text if res.is_error else "UNEXPECTED: the call was not refused",
        ))
    return scenes


# ---------------------------------------------------------------- drawing

WX0, WY0, WX1, WY1 = 72, 56, 1208, 640
PAD = 36


def base(scene_index: int, total: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((WX0, WY0 + 6, WX1, WY1 + 6), 14, fill=SHADOW)  # soft solid shadow
    d.rounded_rectangle((WX0, WY0, WX1, WY1), 14, fill=WINDOW, outline=BORDER)
    for i in range(3):
        d.ellipse((WX0 + 22 + i * 18, WY0 + 17, WX0 + 32 + i * 18, WY0 + 27), fill=DOT)
    title = "salestalk  ·  live MCP tool calls  ·  read-only"
    tw = d.textlength(title, font=F_TITLE)
    d.text(((WX0 + WX1 - tw) / 2, WY0 + 12), title, font=F_TITLE, fill=MUTED)
    d.line((WX0, WY0 + 44, WX1, WY0 + 44), fill=DIVIDER)
    # progress dots for the four questions
    for i in range(total):
        x = WX1 - 30 - (total - 1 - i) * 16
        d.ellipse((x - 4, WY0 + 18, x + 4, WY0 + 26), fill=ACCENT if i <= scene_index else DOT)
    foot = ("Dune & Dhow Trading Co. (fictional)  ·  PostgreSQL  ·  SELECT-only role  ·  "
            "real results from the seeded demo database")
    fw = d.textlength(foot, font=F_FOOT)
    d.text(((W - fw) / 2, WY1 + 26), foot, font=F_FOOT, fill=FAINT)
    return img


def draw_scene(scene: Scene, idx: int, total: int, typed: int, tool: str, rows_shown: float) -> Image.Image:
    """tool: '', 'running' or 'done'. rows_shown: how many result rows are visible (fractional = growing bar)."""
    img = base(idx, total)
    d = ImageDraw.Draw(img)
    x0, x1 = WX0 + PAD, WX1 - PAD
    y = WY0 + 72

    # question bubble (right aligned), typed
    q = scene.question[:typed]
    full_w = d.textlength(scene.question, font=F_Q)
    bx1 = x1
    bx0 = bx1 - full_w - 40
    d.rounded_rectangle((bx0, y, bx1, y + 50), 12, fill=BUBBLE)
    d.text((bx0 + 20, y + 11), q, font=F_Q, fill=INK)
    if typed < len(scene.question):
        cx = bx0 + 20 + d.textlength(q, font=F_Q) + 2
        d.rectangle((cx, y + 13, cx + 2, y + 38), fill=ACCENT)
    y += 78

    if not tool:
        return img

    # tool call chip
    label = scene.call
    cw = d.textlength(label, font=F_MONO) + 56
    d.rounded_rectangle((x0, y, x0 + cw, y + 34), 8, fill=CHIP)
    blocked = scene.refused is not None
    if tool == "running":
        d.arc((x0 + 12, y + 9, x0 + 28, y + 25), 30, 300, fill=CHIP_FUNC, width=2)
    elif blocked:
        d.line((x0 + 14, y + 11, x0 + 26, y + 23), fill=CHIP_NO, width=3)
        d.line((x0 + 26, y + 11, x0 + 14, y + 23), fill=CHIP_NO, width=3)
    else:
        d.line((x0 + 13, y + 17, x0 + 18, y + 22, x0 + 28, y + 12), fill=CHIP_OK, width=3, joint="curve")
    func, _, rest = label.partition("(")
    d.text((x0 + 38, y + 7), func, font=F_MONO, fill=CHIP_FUNC)
    d.text((x0 + 38 + d.textlength(func, font=F_MONO), y + 7), "(" + rest, font=F_MONO, fill=CHIP_TEXT)
    if tool == "done":
        note = f"blocked in {scene.elapsed_ms} ms" if blocked else f"{scene.elapsed_ms} ms"
        d.text((x0 + cw + 14, y + 9), note, font=F_MONO_S, fill=DANGER if blocked else FAINT)
    y += 58

    if tool != "done":
        return img

    if scene.refused is not None:
        if rows_shown <= 0:
            return img
        d.rounded_rectangle((x0, y, x1, y + 128), 10, fill=DANGER_BG, outline=DANGER_BORDER)
        d.text((x0 + 24, y + 18), "Refused", font=F_HEAD, fill=DANGER)
        d.text((x0 + 24, y + 54), scene.refused, font=F_ROW, fill=BODY)
        d.text((x0 + 24, y + 86), "The SQL guard blocks it, and the database role can't write anyway.",
               font=F_ROW, fill=MUTED)
        return img

    d.text((x0, y), scene.headline, font=F_HEAD, fill=INK)
    y += 44
    bar_x0, bar_w = x0 + 560, 300
    for i, row in enumerate(scene.rows):
        if i >= rows_shown:
            break
        grow = min(1.0, rows_shown - i)
        ry = y + i * 52
        if row.rank:
            d.text((x0, ry + 2), row.rank, font=F_MONO, fill=FAINT)
        d.text((x0 + 30, ry), row.label, font=F_ROW_B, fill=INK)
        d.text((x0 + 30, ry + 25), row.sub, font=F_MONO_S, fill=MUTED)
        w = max(6, round(bar_w * row.bar * grow))
        d.rounded_rectangle((bar_x0, ry + 12, bar_x0 + w, ry + 24), 3, fill=ACCENT if i == 0 else ACCENT_SOFT)
        vw = d.textlength(row.value, font=F_MONO)
        d.text((x1 - vw, ry + 8), row.value, font=F_MONO, fill=BODY)
    return img


def frames_for(scene: Scene, idx: int, total: int) -> list[tuple[Image.Image, int]]:
    out: list[tuple[Image.Image, int]] = []
    q = scene.question
    for n in range(0, len(q) + 1, 3):
        out.append((draw_scene(scene, idx, total, n, "", 0), 45))
    out.append((draw_scene(scene, idx, total, len(q), "", 0), 350))
    out.append((draw_scene(scene, idx, total, len(q), "running", 0), 450))
    out.append((draw_scene(scene, idx, total, len(q), "done", 0), 250))
    steps = len(scene.rows) or 1
    for k in range(1, steps * 2 + 1):
        out.append((draw_scene(scene, idx, total, len(q), "done", k / 2), 70))
    out.append((draw_scene(scene, idx, total, len(q), "done", steps + 1), 3200))
    return out


def render(scenes: list[Scene], out_path: Path) -> None:
    frames: list[tuple[Image.Image, int]] = []
    for i, scene in enumerate(scenes):
        frames += frames_for(scene, i, len(scenes))
    # one shared palette built from every scene's final frame, so colours never flicker
    finals = [f for f, ms in frames if ms >= 3000]
    sheet = Image.new("RGB", (W, H * len(finals)))
    for i, f in enumerate(finals):
        sheet.paste(f, (0, i * H))
    # adaptive colours for the anti-aliasing, plus every palette constant pinned exactly
    pinned = [BG, WINDOW, SHADOW, BORDER, DIVIDER, DOT, INK, BODY, MUTED, FAINT, BUBBLE, CHIP, CHIP_TEXT,
              CHIP_FUNC, CHIP_OK, CHIP_NO, ACCENT, ACCENT_SOFT, DANGER, DANGER_BG, DANGER_BORDER]
    adaptive = 128 - len(pinned)
    raw = sheet.quantize(colors=adaptive, method=Image.Quantize.MEDIANCUT).getpalette()[: adaptive * 3]
    colours = [tuple(raw[i : i + 3]) for i in range(0, len(raw), 3)]
    # drop adaptive near-duplicates so the exact constants always win the nearest-colour match
    colours = [c for c in colours if min(sum((a - b) ** 2 for a, b in zip(c, q, strict=True)) for q in pinned) > 120]
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for c in pinned + colours for v in c])
    images = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f, _ in frames]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_path, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames],
                   loop=0, optimize=True, disposal=1)
    print(f"wrote {out_path} ({len(images)} frames, {out_path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "demo.gif"))
    args = parser.parse_args()
    scenes = asyncio.run(collect())
    for s in scenes:
        print(f"{s.call}: {s.elapsed_ms} ms")
    render(scenes, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
