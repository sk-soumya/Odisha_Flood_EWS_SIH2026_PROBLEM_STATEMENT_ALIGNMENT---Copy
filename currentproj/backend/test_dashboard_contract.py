from pathlib import Path


def test_dashboard_uses_valid_backend_and_cdn_urls():
    root = Path(__file__).resolve().parent.parent
    html = (root / "index.html").read_text(encoding="utf-8")

    assert "/api/v1/disaster/predict-live-location" in html
    assert "leaflet@1.9.4/dist/leaflet.css" in html
    assert "leaflet@1.9.4/dist/leaflet.js" in html
    # The dashboard must use a relative/host-derived backend URL
    # so it works both through FastAPI and behind another host/port.
    assert 'window.location.origin' in html
    assert 'http://127.0.0.1:8000' in html
