import sys
import os

APP_DIR = os.path.dirname(__file__)
sys.path.insert(0, APP_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(APP_DIR, '.env'))

import asyncio
from app.main import app


def application(environ, start_response):
    # Build ASGI headers from WSGI environ.
    # WSGI stores most headers as HTTP_* but Content-Type and Content-Length
    # are special — they live at CONTENT_TYPE / CONTENT_LENGTH without the
    # HTTP_ prefix, so we must add them manually.
    headers = []
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            header_name = key[5:].replace('_', '-').lower().encode()
            headers.append((header_name, value.encode()))

    # Forward Content-Type so FastAPI can parse JSON / form bodies correctly
    content_type = environ.get('CONTENT_TYPE', '')
    if content_type:
        headers.append((b'content-type', content_type.encode()))

    # Forward Content-Length
    content_length = environ.get('CONTENT_LENGTH', '')
    if content_length:
        headers.append((b'content-length', content_length.encode()))

    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': environ['REQUEST_METHOD'],
        'headers': headers,
        'path': environ.get('PATH_INFO', '/'),
        'query_string': environ.get('QUERY_STRING', '').encode(),
        'root_path': environ.get('SCRIPT_NAME', ''),
        'scheme': environ.get('wsgi.url_scheme', 'https'),
        'server': (environ.get('SERVER_NAME', 'localhost'), int(environ.get('SERVER_PORT', 80))),
    }

    try:
        cl = int(content_length or 0)
        body = environ['wsgi.input'].read(cl) if cl > 0 else b''
    except Exception:
        body = b''

    response_started = []
    response_body = []

    async def run():
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            if message['type'] == 'http.response.start':
                status_code = message['status']
                raw_headers = [(k.decode(), v.decode()) for k, v in message.get('headers', [])]
                response_started.append((status_code, raw_headers))
            elif message['type'] == 'http.response.body':
                response_body.append(message.get('body', b''))

        await app(scope, receive, send)

    asyncio.run(run())

    status_code, raw_headers = response_started[0]
    status_map = {
        200: '200 OK', 201: '201 Created', 204: '204 No Content',
        400: '400 Bad Request', 401: '401 Unauthorized', 403: '403 Forbidden',
        404: '404 Not Found', 405: '405 Method Not Allowed', 409: '409 Conflict',
        422: '422 Unprocessable Entity', 429: '429 Too Many Requests',
        500: '500 Internal Server Error', 502: '502 Bad Gateway',
        503: '503 Service Unavailable',
    }
    status = status_map.get(status_code, f'{status_code} Unknown')
    start_response(status, raw_headers)
    return response_body
