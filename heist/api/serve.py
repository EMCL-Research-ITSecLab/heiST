"""Production WSGI entry point for the unprivileged browser API.

Configuration is supplied by the service environment. Importing this module
never connects to a database, loads credentials or starts a server.
"""
import os


def options(environ=None):
    environ = os.environ if environ is None else environ
    port = environ.get('HEIST_WEB_PORT', '8001')
    if not isinstance(port, str) or not port.isascii() or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise ValueError('HEIST_WEB_PORT must be an unprivileged TCP port')
    return {'bind': '127.0.0.1:'+str(int(port)), 'workers': 2, 'worker_class': 'gthread', 'threads': 4,
            'timeout': 1300, 'graceful_timeout': 30, 'keepalive': 5,
            'max_requests': 1000, 'max_requests_jitter': 100,
            'limit_request_line': 4094, 'limit_request_fields': 100, 'limit_request_field_size': 8190,
            'forwarded_allow_ips': '127.0.0.1', 'proxy_protocol': False,
            'accesslog': None, 'errorlog': '-', 'loglevel': 'warning', 'umask': 0o077,
            'preload_app': False}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    from gunicorn.app.base import BaseApplication

    class WebApplication(BaseApplication):
        def load_config(self):
            for name, value in options().items():
                self.cfg.set(name, value)

        def load(self):
            from heist.api.public import create_app
            return create_app()

    WebApplication().run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
