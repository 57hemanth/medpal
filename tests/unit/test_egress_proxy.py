"""The allowlisting egress proxy: tunnels only to allowlisted host:port, refuses everything else."""

import asyncio

import pytest

from services.egress_proxy.proxy import parse_allowlist, serve


async def _upstream():
    async def echo(r, w):
        w.write(b"pong:" + await r.read(4))
        await w.drain()
        w.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _connect(proxy_port: int, target: str) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await w.drain()
    return await r.readuntil(b"\r\n\r\n"), r, w


async def test_allowlisted_destination_is_tunnelled():
    upstream, up_port = await _upstream()
    proxy = await serve("127.0.0.1", 0, parse_allowlist(f"127.0.0.1:{up_port}"))
    port = proxy.sockets[0].getsockname()[1]
    async with upstream, proxy:
        status, r, w = await _connect(port, f"127.0.0.1:{up_port}")
        assert status.startswith(b"HTTP/1.1 200")
        w.write(b"ping")
        await w.drain()
        assert await r.read(100) == b"pong:ping"
        w.close()


@pytest.mark.parametrize("target", ["evil.example.com:443", "127.0.0.1:5432"])
async def test_anything_not_allowlisted_is_refused(target):
    proxy = await serve("127.0.0.1", 0, parse_allowlist("api.openai.com:443"))
    port = proxy.sockets[0].getsockname()[1]
    async with proxy:
        status, _, w = await _connect(port, target)
        assert status.startswith(b"HTTP/1.1 403")
        w.close()


async def test_plain_http_is_refused():
    proxy = await serve("127.0.0.1", 0, parse_allowlist("api.openai.com:443"))
    port = proxy.sockets[0].getsockname()[1]
    async with proxy:
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"GET http://api.openai.com/ HTTP/1.1\r\nHost: api.openai.com\r\n\r\n")
        await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 405")
        w.close()


def test_allowlist_parsing_is_strict():
    assert parse_allowlist("API.OpenAI.com:443, x.y:8443") == {("api.openai.com", 443), ("x.y", 8443)}
    with pytest.raises(ValueError):
        parse_allowlist("no-port-here")
