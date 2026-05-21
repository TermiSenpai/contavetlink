"""Genera `app/static/icon.ico` a partir de `app/static/icon.svg`.

El SVG es la fuente de verdad del diseño; el ICO es un artefacto de build que
PyInstaller incrusta en el .exe (no se commitea). `build.bat` lo regenera
antes de cada build.

Uso:
    python scripts/build_icon.py
    python scripts/build_icon.py --sizes 16 32 48 64 128 256

Dependencias (requirements-dev.txt): PyMuPDF (rasterizado SVG), Pillow (ensamblado ICO).
Ambos wheels puros en Windows — sin dependencias del sistema (sin cairo/GTK).

Limitación: MuPDF no soporta SVG <linearGradient>/<radialGradient> y los rinde
como negro. El fondo del icono (gradiente esmeralda + esquinas redondeadas) se
pinta con Pillow, y solo la pata (colores planos) se rasteriza con PyMuPDF;
después se componen.
"""
from __future__ import annotations

import argparse
import re
import sys
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "app" / "static" / "icon.svg"
ICO_PATH = ROOT / "app" / "static" / "icon.ico"
DEFAULT_SIZES = (16, 32, 48, 64, 128, 256)

# Espejo de los stops del <linearGradient id="bg"> del SVG (de 0%, 55%, 100%).
# Si cambias colores en icon.svg, cámbialos también aquí.
BG_GRADIENT_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.00, (0x0F, 0x76, 0x6E)),
    (0.55, (0x0B, 0x5E, 0x58)),
    (1.00, (0x06, 0x4E, 0x3B)),
)
CORNER_RADIUS_RATIO = 112 / 512  # rx="112" sobre viewBox 512


def _interp_color(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    stops = BG_GRADIENT_STOPS
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))  # type: ignore[return-value]
    return stops[-1][1]


def render_gradient_tile(size: int) -> Image.Image:
    """Tile esmeralda con gradiente diagonal (TL→BR) y esquinas redondeadas."""
    tile = Image.new("RGB", (size, size))
    px = tile.load()
    max_d = 2 * (size - 1) if size > 1 else 1
    for y in range(size):
        for x in range(size):
            px[x, y] = _interp_color((x + y) / max_d)

    radius = round(size * CORNER_RADIUS_RATIO)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(tile, (0, 0), mask)
    return out


_BG_RECT_RE = re.compile(
    r'<rect\b[^>]*\bfill="url\(#(?:bg|glow)\)"[^>]*/>',
    re.IGNORECASE,
)


def _strip_gradient_backgrounds(svg_text: str) -> str:
    """Quita los <rect fill="url(#bg|glow)"/> para que MuPDF no los pinte negros."""
    return _BG_RECT_RE.sub("", svg_text)


def render_foreground(svg_path: Path, size: int) -> Image.Image:
    """Rasteriza el SVG sin sus fondos gradiente — solo la pata sobre transparente."""
    svg_text = _strip_gradient_backgrounds(svg_path.read_text(encoding="utf-8"))
    with fitz.open(stream=svg_text.encode("utf-8"), filetype="svg") as doc:
        page = doc[0]
        scale = size / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
    return Image.open(BytesIO(pix.tobytes("png"))).convert("RGBA")


def render_master(svg_path: Path, size: int) -> Image.Image:
    """Compone fondo (Pillow) + foreground (PyMuPDF) en una imagen `size`x`size`."""
    base = render_gradient_tile(size)
    fg = render_foreground(svg_path, size)
    base.alpha_composite(fg)
    return base


def build_ico(svg_path: Path, ico_path: Path, sizes: tuple[int, ...]) -> None:
    if not svg_path.exists():
        raise FileNotFoundError(f"No existe {svg_path}")

    master = render_master(svg_path, max(sizes))
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    # bitmap_format="bmp": fuerza DIB en todas las entradas. Por defecto Pillow 10
    # codifica las entradas como PNG, pero Windows Explorer no renderiza iconos
    # PNG-encoded incrustados en RT_ICON a tamaños pequeños (16/32/48), por lo
    # que el .exe se muestra con el icono genérico aunque el recurso esté presente.
    master.save(ico_path, format="ICO", sizes=[(s, s) for s in sizes], bitmap_format="bmp")
    print(f"[build_icon] OK -> {ico_path.relative_to(ROOT)} ({', '.join(map(str, sizes))})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera icon.ico desde icon.svg")
    parser.add_argument("--svg", type=Path, default=SVG_PATH)
    parser.add_argument("--ico", type=Path, default=ICO_PATH)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    args = parser.parse_args()

    try:
        build_ico(args.svg, args.ico, tuple(sorted(set(args.sizes))))
    except Exception as exc:
        print(f"[build_icon] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
