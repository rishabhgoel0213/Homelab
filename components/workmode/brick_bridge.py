"""Tailnet-only Brick observation relay. Never turns loss of contact into unbrick."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import websocket


def tailnet(address):
    ip = ipaddress.ip_address(address)
    return ip in ipaddress.ip_network('100.64.0.0/10') or ip in ipaddress.ip_network('fd7a:115c:a1e0::/48')


class State:
    def __init__(self, path, clock=time.monotonic):
        self.path, self.clock = Path(path), clock
        self.lock = threading.Lock()
        self.value, self.seen = 'unknown', None
        self.version_tested = None
        self.latched = False
        if self.path.exists():
            self.latched = json.loads(self.path.read_text())['latchedBricked']
            if type(self.latched) is not bool:
                raise ValueError('Invalid persisted latch')

    def observe(self, data):
        if data.get('event') == 'ready':
            return
        value = data.get('state')
        if (data.get('event') != 'state' or data.get('capability') != 'brick'
                or data.get('source') != 'accessibility_service_configuration'
                or value not in ('bricked', 'unbricked', 'unknown')):
            self.disconnect()
            return
        with self.lock:
            if value in ('bricked', 'unbricked'):
                latched = value == 'bricked'
                if latched != self.latched or not self.path.exists():
                    temp = self.path.with_suffix('.tmp')
                    with temp.open('w') as f:
                        json.dump({'latchedBricked': latched}, f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, self.path)
                    self.latched = latched
            self.value, self.seen = value, self.clock()
            self.version_tested = data.get('versionTested')

    def disconnect(self):
        with self.lock:
            self.value, self.seen = 'unknown', None

    def snapshot(self):
        with self.lock:
            age = None if self.seen is None else max(0, self.clock() - self.seen)
            return {'schema': 1, 'state': self.value if age is not None and age <= 10 else 'unknown',
                    'latchedBricked': self.latched, 'ageSeconds': age,
                    'versionTested': self.version_tested}


def follow(state, host, port, token_file):
    while True:
        ws = None
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not addresses or not all(tailnet(a[4][0]) for a in addresses):
                raise ValueError('Phone must resolve exclusively to Tailscale addresses')
            # Pin the resolved IP and bypass proxy environment; never send credentials to a proxy.
            ip = addresses[0][4][0]
            authority = f'[{ip}]' if ':' in ip else ip
            token = Path(token_file).read_text().strip()
            if len(token) < 16 or '\n' in token or '\r' in token:
                raise ValueError('Invalid phone credential')
            ws = websocket.create_connection(f'ws://{authority}:{port}/brick/state',
                header={'Authorization': 'Bearer ' + token}, timeout=8,
                http_no_proxy=['*'], enable_multithread=True)
            while True:
                raw = ws.recv()
                if not isinstance(raw, str) or not raw or len(raw) > 16384:
                    raise ValueError('Invalid phone message')
                state.observe(json.loads(raw))
        except Exception:
            # Exception text may contain handshake headers; do not log it.
            state.disconnect()
        finally:
            if ws:
                ws.close()
        time.sleep(3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bind', default='100.73.159.103')
    p.add_argument('--port', type=int, default=8127)
    p.add_argument('--phone', default='100.84.182.122')
    p.add_argument('--token-file', required=True)
    p.add_argument('--state-file', required=True)
    args = p.parse_args()
    if not tailnet(args.bind):
        p.error('Bind address must belong to Tailscale')
    state = State(args.state_file)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.client_address[0] not in ('100.105.159.13', '100.73.159.103'):
                self.send_error(403)
                return
            if self.path != '/state':
                self.send_error(404)
                return
            payload = json.dumps(state.snapshot()).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *_):
            pass
    threading.Thread(target=follow, args=(state, args.phone, 8080, args.token_file), daemon=True).start()
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
