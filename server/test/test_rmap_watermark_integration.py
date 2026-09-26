from unittest.mock import MagicMock

import pymupdf
from flask import Flask

import app.rmap.routes as rmap_routes
from app.rmap import bp as rmap_blueprint
from app.watermarking.utils import read_watermark


def _create_source_pdf(path):
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=300)
        page.draw_rect(
            pymupdf.Rect(20, 20, 280, 200),
            fill=(0.2, 0.5, 0.8),
        )
        page.insert_text(
            (45, 140),
            "RMAP integration test",
            fontsize=18,
            color=(1, 1, 1),
        )
        document.save(path)


def test_rmap_creates_extractable_rgb_dft_qim_pdf(tmp_path, monkeypatch):
    source_pdf = tmp_path / "source.pdf"
    storage_dir = tmp_path / "storage"
    key_path = tmp_path / "watermarking-key"

    storage_dir.mkdir()
    _create_source_pdf(source_pdf)
    key_path.write_text("integration-master-key", encoding="utf8")

    document_id = 42
    identity = "recipient@example.com"
    expected_link = "integration-test-link"
    response_payload = {"link": expected_link}

    rmap_server = MagicMock()
    rmap_server.receiveMsg2.return_value = (
        identity,
        expected_link,
        response_payload,
    )

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        STORAGE_DIR=storage_dir,
        RMAP_WATERMARK_METHOD="rgb-dft-qim-v1",
        RMAP_WATERMARKING_KEY_PATH=str(key_path),
    )
    app.extensions["rmap-server"] = rmap_server
    app.extensions["rmap-document-id"] = document_id
    app.register_blueprint(rmap_blueprint)

    registered_version = {}

    monkeypatch.setattr(
        rmap_routes,
        "_check_link_collision",
        lambda _link: False,
    )
    monkeypatch.setattr(
        rmap_routes,
        "get_source_document_path",
        lambda _app, _document_id: source_pdf,
    )

    def capture_registered_version(**values):
        registered_version.update(values)

    monkeypatch.setattr(
        rmap_routes,
        "_register_version",
        capture_registered_version,
    )

    response = app.test_client().post(
        "/api/rmap-get-link",
        json={"message": "test"},
    )

    assert response.status_code == 200
    assert response.get_json() == response_payload
    rmap_server.receiveMsg2.assert_called_once_with({"message": "test"})

    watermarked_pdf = storage_dir / f"{expected_link}.pdf"

    assert watermarked_pdf.exists()
    assert registered_version["document_id"] == document_id
    assert registered_version["intended_for"] == identity
    assert registered_version["method"] == "rgb-dft-qim-v1"
    assert registered_version["path"] == str(watermarked_pdf)

    watermark_key = rmap_routes._derive_key(
        "integration-master-key",
        document_id,
        identity,
        expected_link,
    )

    assert read_watermark(
        "rgb-dft-qim-v1",
        watermarked_pdf,
        watermark_key,
    ) == registered_version["secret"]
