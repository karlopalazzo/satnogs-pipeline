from pathlib import Path

from decode_meteor import choose_upload_image


def _touch(path: Path, size: int = 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def test_prefers_3a21_composite(tmp_path: Path) -> None:
    msu = tmp_path / "MSU-MR"
    _touch(msu / "MSU-MR-1.png")
    _touch(msu / "msu_mr_AVHRR_3a21_False_Color_(uncalibrated).png")
    chosen = choose_upload_image(tmp_path)
    assert chosen.name == "msu_mr_AVHRR_3a21_False_Color_(uncalibrated).png"


def test_prefers_msu_mr_composite_over_single_channel(tmp_path: Path) -> None:
    msu = tmp_path / "MSU-MR"
    _touch(msu / "MSU-MR-1.png")
    _touch(msu / "msu_mr_AVHRR_124_False_Color_(Cloud_RGB).png")
    chosen = choose_upload_image(tmp_path)
    assert chosen.name == "msu_mr_AVHRR_124_False_Color_(Cloud_RGB).png"


def test_builds_221_when_only_visible_channels(tmp_path: Path) -> None:
    from PIL import Image

    msu = tmp_path / "MSU-MR"
    msu.mkdir()
    Image.new("L", (8, 4), 30).save(msu / "MSU-MR-1.png")
    Image.new("L", (8, 4), 200).save(msu / "MSU-MR-2.png")
    Image.new("L", (8, 4), 100).save(msu / "MSU-MR-4.png")
    chosen = choose_upload_image(tmp_path)
    assert chosen is not None
    assert chosen.name.startswith("upload_AVHRR_221")
    assert chosen.stat().st_size > 0
