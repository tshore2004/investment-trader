from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from src.dashboard.app import create_app


def test_index_serves_new_ui_by_default() -> None:
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_legacy_query_param_serves_legacy_html() -> None:
    client = TestClient(create_app())
    resp = client.get("/?legacy=1")
    legacy_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "src" / "dashboard" / "templates" / "index_legacy.html"
    )
    assert resp.status_code == 200
    assert resp.text == legacy_path.read_text(encoding="utf-8")


def test_static_js_directory_is_mounted() -> None:
    client = TestClient(create_app())
    static_dir = (
        pathlib.Path(__file__).parent.parent.parent
        / "src" / "dashboard" / "static" / "js"
    )
    static_dir.mkdir(parents=True, exist_ok=True)
    probe = static_dir / "_mount_probe.js"
    probe.write_text("export const probe = true;\n", encoding="utf-8")
    try:
        resp = client.get("/static/js/_mount_probe.js")
        assert resp.status_code == 200
        assert "probe" in resp.text
    finally:
        probe.unlink()
