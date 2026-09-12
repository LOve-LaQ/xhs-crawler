from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def list_image_assets(folder: str | Path) -> list[Path]:
    """Return supported image files in one local folder, sorted by name."""
    path = Path(folder)
    if not path.is_dir():
        return []
    return sorted(
        (
            item
            for item in path.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda item: item.name.lower(),
    )
