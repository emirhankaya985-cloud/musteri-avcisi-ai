"""DNS/TCP/TLS-only diagnostics for fixed public Render health hosts.

A transport handshake is not HTTP health, OAuth readiness, or CRM permission.
No response bodies, tokens, customer data, redirects or alternative URLs.
"""
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

from .unified_control import SERVICES


def inspect_layers(name, resolver=socket.getaddrinfo,
                   dialer=socket.create_connection,
                   ssl_factory=ssl.create_default_context):
    if name not in SERVICES:
        return "unknown_service"
    parsed = urlsplit(SERVICES[name]["url"])
    host = parsed.hostname
    if (parsed.scheme != "https" or parsed.port is not None
            or not host or not host.endswith(".onrender.com")
            or parsed.username or parsed.password):
        return "configuration_rejected"
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        return "dns_failure"
    public_ips = []
    for record in records:
        try:
            ip = ipaddress.ip_address(record[4][0])
            if ip.is_global:
                public_ips.append(str(ip))
        except (ValueError, IndexError, TypeError):
            continue
    if not public_ips:
        return "dns_no_public_address"
    conn = None
    wrapped = None
    try:
        # Connect to resolved address, not a second DNS lookup. TLS SNI and
        # certificate hostname remain the original, fixed Render hostname.
        conn = dialer((public_ips[0], 443), timeout=4)
    except TimeoutError:
        return "tcp_timeout"
    except ConnectionRefusedError:
        return "tcp_refused"
    except OSError:
        return "tcp_failure"
    try:
        wrapped = ssl_factory().wrap_socket(conn, server_hostname=host)
        return "tls_ok"
    except ssl.SSLCertVerificationError:
        return "tls_certificate"
    except (ssl.SSLError, TimeoutError):
        return "tls_handshake"
    except OSError:
        return "tls_network"
    finally:
        if wrapped is not None:
            wrapped.close()
        elif conn is not None:
            conn.close()


def run(output=print):
    states = {name: inspect_layers(name) for name in SERVICES}
    for name, state in states.items():
        output(f"RENDER_NETWORK_LAYERS: service={name}; phase={state}; "
               "http_health_separately_required=1; customer_writes=0")
    return states


if __name__ == "__main__":
    run()
