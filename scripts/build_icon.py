"""Generate the Empire application icon (build-time only)."""

from pathlib import Path

from PIL import Image, ImageDraw

ASSET_DIR = Path(__file__).resolve().parents[1] / "src" / "empire" / "desktop" / "assets"
CANVAS_SIZE = 1024
OUTPUT_SIZE = 256


def scaled_box(box: tuple[int, int, int, int], scale: int) -> tuple[int, int, int, int]:
    return tuple(value * scale for value in box)


def build_icon() -> Image.Image:
    """Draw a compact E monogram crossed by an upward research trend."""
    scale = CANVAS_SIZE // OUTPUT_SIZE
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        scaled_box((8, 8, 248, 248), scale),
        radius=48 * scale,
        fill="#17243A",
    )

    # The three research layers form a clear E at small taskbar sizes.
    pale_blue = "#EAF2FF"
    draw.rounded_rectangle(scaled_box((56, 52, 82, 204), scale), radius=13 * scale,
                           fill=pale_blue)
    for box in ((68, 52, 194, 80), (68, 114, 166, 142), (68, 176, 202, 204)):
        draw.rounded_rectangle(scaled_box(box, scale), radius=14 * scale, fill=pale_blue)

    # A warm trend line gives the research mark a distinct, optimistic accent.
    points = [(104, 181), (145, 137), (190, 70)]
    draw.line([(x * scale, y * scale) for x, y in points], fill="#F4B942",
              width=12 * scale, joint="curve")
    for x, y in points:
        draw.ellipse(
            scaled_box((x - 10, y - 10, x + 10, y + 10), scale),
            fill="#F4B942",
            outline="#17243A",
            width=3 * scale,
        )

    return image.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    image = build_icon()
    image.save(ASSET_DIR / "empire.png", optimize=True)
    image.save(
        ASSET_DIR / "empire.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
