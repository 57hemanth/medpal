"""Allowlisting HTTPS egress proxy (HTTP CONNECT only).

Containers inside the boundary sit on an internal network with no route out. Their only path to the
internet is this proxy, which tunnels TLS to allowlisted host:port pairs (the configured model APIs)
and refuses everything else. It never sees content (the tunnel is end-to-end TLS) and logs only the
destination host and the decision.

    MEDPAL_EGRESS_ALLOWLIST="generativelanguage.googleapis.com:443,api.openai.com:443" \\
        uv run python -m services.egress_proxy.proxy --port 8888
"""

import argparse
import asyncio
import logging
import os

log = logging.getLogger("medpal.egress")
MAX_HEADER_BYTES = 8192


def parse_allowlist(value: str) -> frozenset[tuple[str, int]]:
    pairs = set()
    for item in filter(None, (part.strip() for part in value.split(","))):
        host, _, port = item.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"allowlist entries must be host:port, got {item!r}")
        pairs.add((host.lower(), int(port)))
    return frozenset(pairs)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


def make_handler(allowlist: frozenset[tuple[str, int]]):  # type: ignore[no-untyped-def]
    async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            client_w.close()
            return
        if len(head) > MAX_HEADER_BYTES:
            client_w.close()
            return
        method, _, rest = head.split(b"\r\n", 1)[0].decode("latin-1").partition(" ")
        target = rest.split(" ", 1)[0]
        host, _, port_text = target.rpartition(":")
        if method != "CONNECT" or not port_text.isdigit():
            log.warning("egress refused: non-CONNECT request %s", method)
            client_w.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            await client_w.drain()
            client_w.close()
            return
        destination = (host.lower(), int(port_text))
        if destination not in allowlist:
            log.warning("egress refused: %s:%s not allowlisted", *destination)
            client_w.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await client_w.drain()
            client_w.close()
            return
        try:
            upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(*destination), timeout=10)
        except (OSError, TimeoutError):
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await client_w.drain()
            client_w.close()
            return
        log.info("egress allowed: %s:%s", *destination)
        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_w.drain()
        await asyncio.gather(_pipe(client_r, upstream_w), _pipe(upstream_r, client_w))

    return handle


async def serve(host: str, port: int, allowlist: frozenset[tuple[str, int]]) -> asyncio.Server:
    return await asyncio.start_server(make_handler(allowlist), host, port)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - listens on the boundary network only
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    allowlist = parse_allowlist(os.environ.get("MEDPAL_EGRESS_ALLOWLIST", ""))
    log.info(
        "egress allowlist: %s", ", ".join(f"{h}:{p}" for h, p in sorted(allowlist)) or "(empty: deny all)"
    )

    async def run() -> None:
        server = await serve(args.host, args.port, allowlist)
        async with server:
            await server.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":
    main()
