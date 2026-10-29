from types import SimpleNamespace

from fastapi.testclient import TestClient
from pokeldn.web.live import LiveTrading


def install(monkeypatch, tmp_path, devices, *, supported=True, mode='bank'):
    import importlib
    module = importlib.import_module('pokeldn.web.app')
    monkeypatch.setattr(module, 'LiveTrading', lambda store:LiveTrading(store, host_check=lambda:supported, devices=devices))
    return TestClient(module.create_app(data_dir=tmp_path, mode=mode))


def test_hardware_and_health_follow_connect_disconnect_and_reconnect(monkeypatch,tmp_path):
    ports = []
    client = install(monkeypatch,tmp_path,lambda:list(ports))
    assert client.get('/api/hardware').json()['hardware_status']=='disconnected'
    ports.append({'device':'/dev/ttyACM0','description':'Native USB','serial_number':'TEST'})
    for path in ('/api/hardware','/api/health'):
        result=client.get(path)
        assert result.json()['hardware_connected'] is True
        assert result.json()['hardware_status']=='connected'
        assert result.headers['Cache-Control']=='no-store'
    ports.clear()
    assert client.get('/api/hardware').json()['hardware_status']=='disconnected'
    assert client.get('/api/health').json()['hardware_connected'] is False
    ports.append({'device':'/dev/ttyACM1','description':'Native USB','serial_number':'TEST'})
    assert client.get('/api/hardware').json()['devices'][0]['device']=='/dev/ttyACM1'


def test_hardware_poll_only_enumerates_without_opening_serial(monkeypatch,tmp_path):
    from serial.tools import list_ports
    import serial
    import importlib
    module=importlib.import_module('pokeldn.web.app')
    monkeypatch.setattr(list_ports,'comports',lambda:[SimpleNamespace(device='/dev/ttyACM0',description='Native USB',serial_number='TEST',vid=0x303a,pid=0x1001)])
    monkeypatch.setattr(serial,'Serial',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('must not open the serial port')))
    monkeypatch.setattr(module,'LiveTrading',lambda store:LiveTrading(store,host_check=lambda:True))
    client=TestClient(module.create_app(data_dir=tmp_path))
    assert client.get('/api/hardware').json()['hardware_connected'] is True


def test_enumeration_failure_is_unavailable_instead_of_disconnected(monkeypatch,tmp_path):
    def fail():raise OSError('test enumeration failure')
    client=install(monkeypatch,tmp_path,fail)
    result=client.get('/api/hardware')
    assert result.status_code==200
    assert result.json()=={'hardware_connected':False,'hardware_status':'unavailable','devices':[]}
    assert client.get('/api/health').json()['status']=='ok'


def test_demo_and_unsupported_hosts_do_not_probe_hardware(monkeypatch,tmp_path):
    def fail():raise AssertionError('must not enumerate')
    client=install(monkeypatch,tmp_path,fail,mode='demo')
    assert client.get('/api/hardware').json()['hardware_status']=='demo'
    assert client.get('/api/health').json()['hardware_connected'] is False
    client=install(monkeypatch,tmp_path/'unsupported',fail,supported=False)
    assert client.get('/api/hardware').json()['hardware_status']=='unsupported'
