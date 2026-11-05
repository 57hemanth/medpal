"""Prove the egress boundary from inside the running API container (after `make up-boundary`).

1. A direct connection to the internet must FAIL (internal network: no route out).
2. A tunnel through the egress proxy to a non-allowlisted host must be REFUSED (403).
3. A tunnel to an allowlisted model API must be ESTABLISHED (200).

Exit code 1 if any check fails.
"""

import subprocess
import sys

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "infra/docker-compose.boundary.yml",
    "exec",
    "-T",
    "api",
    "python",
    "-c",
]

DIRECT = """
import socket
try:
    socket.create_connection(("example.com", 443), timeout=5).close()
    print("REACHED")
except OSError as e:
    print("BLOCKED", type(e).__name__)
"""

VIA_PROXY = """
import socket, sys
s = socket.create_connection(("egress", 8888), timeout=5)
target = sys.argv[1]
s.sendall(f"CONNECT {target} HTTP/1.1\\r\\nHost: {target}\\r\\n\\r\\n".encode())
print(s.recv(64).split(b"\\r\\n")[0].decode())
"""


def run(code: str, *args: str) -> str:
    result = subprocess.run([*COMPOSE, code, *args], capture_output=True, text=True, timeout=60)  # noqa: S603
    return (result.stdout or result.stderr).strip()


def main() -> None:
    checks = [
        ("direct internet access is blocked", run(DIRECT), lambda out: out.startswith("BLOCKED")),
        (
            "non-allowlisted host is refused",
            run(VIA_PROXY, "example.com:443"),
            lambda out: " 403 " in f" {out} ",
        ),
        (
            "allowlisted model API is reachable",
            run(VIA_PROXY, "api.openai.com:443"),
            lambda out: " 200 " in f" {out} ",
        ),
    ]
    failed = False
    for name, output, ok in checks:
        passed = ok(output)
        failed |= not passed
        print(f"{'PASS' if passed else 'FAIL'}  {name}  ({output})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
