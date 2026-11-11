"""One production worker, explicit dual-stack socket, native Uvicorn shutdown."""
import os
import socket

import uvicorn


def listen_socket(port: int) -> socket.socket:
    if socket.has_dualstack_ipv6():
        return socket.create_server(("::", port), family=socket.AF_INET6, dualstack_ipv6=True)
    return socket.create_server(("0.0.0.0", port))


def main() -> None:
    # Explicit IPV6_V6ONLY=0 avoids framework/platform-dependent IPv6-only binds.
    with listen_socket(int(os.environ.get("PORT", "8010"))) as listener:
        uvicorn.run("app.main:app", fd=listener.fileno(), proxy_headers=True)


if __name__ == "__main__":
    main()
