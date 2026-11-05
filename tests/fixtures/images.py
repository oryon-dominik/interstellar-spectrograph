from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def portrait(tmp_path: Path) -> Path:
    """A 1024×768 PNG with a transparent corner, standing in for an original."""
    path = tmp_path / "portrait.png"
    image = Image.new("RGBA", (1024, 768), (134, 26, 34, 255))
    image.paste((0, 0, 0, 0), (0, 0, 64, 64))
    image.save(path, format="PNG")
    return path
