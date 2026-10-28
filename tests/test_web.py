"""Website demo contract and production static hosting; never touches the real Bank."""
from fastapi.testclient import TestClient
from pokeldn.web.app import create_app


def test_demo_boxes_are_stable_and_read_only():
    client = TestClient(create_app(mode="demo"))
    boxes = client.get('/api/boxes').json()
    assert len(boxes) == 4
    assert all(len(box['slots']) == 30 for box in boxes)
    pokemon = [p for b in boxes for p in b['slots'] if p]
    assert len(pokemon) == 12
    assert len({p['id'] for p in pokemon}) == 12
    assert all(p['trainer'] == 'DEMO' for p in pokemon)
    assert client.get('/api/boxes/1').json() == boxes[0]
    assert client.get('/api/boxes/99').status_code == 404
    assert client.post('/api/boxes', json={}).status_code == 403
    assert client.get('/api/boxes').json() == boxes
    assert client.get('/api/health').json()['mode'] == 'demo'
    assert client.get('/api/history').json()['entries'] == []


def test_static_frontend_does_not_swallow_missing_api_or_assets(tmp_path):
    (tmp_path / 'index.html').write_text('<html>PkMn-SBank</html>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/app.js').write_text('console.log("demo")')
    client = TestClient(create_app(tmp_path))
    assert client.get('/').text == '<html>PkMn-SBank</html>'
    assert 'console.log' in client.get('/assets/app.js').text
    assert client.get('/api/missing').status_code == 404
    assert client.get('/api/missing').headers['content-type'] == 'application/json'
    assert client.get('/assets/missing.js').status_code == 404
    assert client.get('/%2e%2e/README.md').status_code == 404


def test_unbuilt_frontend_gives_setup_instructions(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert 'npm ci' in client.get('/').json()['message']
    assert client.get('/api/health').status_code == 200
