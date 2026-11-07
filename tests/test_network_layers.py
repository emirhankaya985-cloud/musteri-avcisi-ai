"""Transport stage is not confused with HTTP, secrets or CRM readiness."""
import socket
import ssl
import unittest
from leadhunter.network_layers import inspect_layers


class Conn:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


class TLS:
    def __init__(self, fail=False):
        self.fail = fail
    def wrap_socket(self, conn, server_hostname):
        assert server_hostname.endswith('.onrender.com')
        if self.fail:
            raise ssl.SSLError('synthetic')
        return conn


def resolver(host, port, type):
    assert type == socket.SOCK_STREAM
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '',
             ('8.8.8.8', port))]


class NetworkLayerTests(unittest.TestCase):
    def test_healthy_transport_is_not_http_success(self):
        conn = Conn()
        result = inspect_layers('isletmepilot', resolver,
                                lambda address,timeout:conn,
                                lambda:TLS())
        self.assertEqual(result,'tls_ok')
        self.assertTrue(conn.closed)

    def test_dns_failure_is_classified_without_network(self):
        def bad(*args,**kwargs):
            raise socket.gaierror('synthetic')
        self.assertEqual(inspect_layers('yorumpilot',bad), 'dns_failure')

    def test_private_dns_address_is_never_connected(self):
        private = lambda h,p,type: [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        self.assertEqual(inspect_layers('yorumpilot',private,
                         lambda *args: self.fail('unsafe dial')),
                         'dns_no_public_address')

    def test_tcp_timeout_is_distinct_from_tls_failure(self):
        def timeout(*args,**kwargs):
            raise TimeoutError('synthetic')
        self.assertEqual(inspect_layers('isletmepilot',resolver,timeout),
                         'tcp_timeout')
        conn = Conn()
        self.assertEqual(inspect_layers('yorumpilot',resolver,
                         lambda *args:conn,lambda:TLS(fail=True)),
                         'tls_handshake')
        self.assertTrue(conn.closed)


if __name__ == '__main__':
    unittest.main()
