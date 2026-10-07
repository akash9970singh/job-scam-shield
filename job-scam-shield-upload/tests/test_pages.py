import pytest
from fastapi.testclient import TestClient

from app.main import PAGES, app

client = TestClient(app)


@pytest.mark.parametrize("path", list(PAGES))
def test_every_page_loads_with_shared_layout(path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "/static/css/style.css" in resp.text
    assert "/static/js/common.js" in resp.text


def test_home_links_to_every_feature():
    html = client.get("/").text
    for path in PAGES:
        if path != "/":
            assert f'href="{path}"' in html, path


def test_shared_assets_are_served():
    assert client.get("/static/css/style.css").status_code == 200
    assert "window.JSS" in client.get("/static/js/common.js").text


def test_sample_letters():
    resp = client.get("/samples/letters/fake_offer_brightwave.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.parametrize("name", ["nope.pdf", "..%2F..%2FREADME.md", "%2E%2E%2Fpytest.ini"])
def test_sample_letters_rejects_anything_else(name):
    assert client.get(f"/samples/letters/{name}").status_code == 404
