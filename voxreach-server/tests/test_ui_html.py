from pathlib import Path

UI_HTML = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def test_ui_has_secret_input_and_get_token_button():
    html = UI_HTML.read_text()

    assert 'id="uiSecret"' in html
    assert "requestToken()" in html


def test_ui_request_token_function_calls_token_endpoint():
    html = UI_HTML.read_text()

    assert "async function requestToken()" in html
    assert "fetch('/api/token'" in html
    assert "document.getElementById('connUrl').value = data.url" in html
    assert "document.getElementById('connToken').value = data.token" in html
