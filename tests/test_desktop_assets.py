from desktop.assets import list_image_assets


def test_list_image_assets_filters_and_sorts_files(tmp_path) -> None:
    (tmp_path / "02-product.PNG").write_bytes(b"")
    (tmp_path / "01-product.jpg").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "03-product.webp").write_bytes(b"")

    assert [item.name for item in list_image_assets(tmp_path)] == [
        "01-product.jpg",
        "02-product.PNG",
    ]
