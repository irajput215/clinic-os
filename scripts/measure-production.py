#!/usr/bin/env python3
"""Measure the deployed app at the origin, not from wherever this script happens to run.

Judging speed by the total time a request takes measures the distance between the observer and
the app as much as the app. This script reports what is location independent instead:

- ``upstream``: FastAPI Cloud's ``x-envoy-upstream-service-time``, the time the request spent in
  the app process, measured by the platform's own proxy.
- ``Server-Timing`` (``app``, ``db``, ``db-connect``, ``db-rt``) where the app sends it: the
  readiness probe always, and the authenticated reads when a probe account is configured
  (``PROBE_EMAIL`` / ``PROBE_PASSWORD``, one clearly named probe clinic; never a real tenant).
- the cache and compression headers of the app's static files.

``total`` is printed too, for the record, and labelled as including the observer's own distance.
Standard library only: it runs on a bare CI runner. Every request is a read; nothing is written
except the probe account's own sign-in.

Usage: ``python scripts/measure-production.py [--base-url URL] [--samples N]``. A Markdown report is
written to stdout and, in GitHub Actions, to the job summary.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

DEFAULT_BASE_URL = "https://clinic-os.fastapicloud.dev"
API = "/api/v1"
UPSTREAM_HEADER = "x-envoy-upstream-service-time"


@dataclass
class Sample:
    status: int
    total_ms: float
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def upstream_ms(self) -> float | None:
        value = self.headers.get(UPSTREAM_HEADER)
        return float(value) if value else None

    def timing(self, metric: str) -> float | None:
        """A `Server-Timing` metric's `dur`, or its `desc` when it is a count (`db-rt`)."""
        header = self.headers.get("server-timing", "")
        match = re.search(
            rf'(?:^|, ){re.escape(metric)};(?:dur=([\d.]+)|desc="(\d+)")', header
        )
        if not match:
            return None
        return float(match.group(1) or match.group(2))


def fetch(
    url: str, *, headers: dict[str, str] | None = None, data: str | None = None
) -> Sample:
    """One request through curl, so the timing is curl's, with a fresh connection each time."""
    command = [
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-D",
        "-",
        "--max-time",
        "30",
        "-w",
        "\n__total__=%{time_total}\n",
    ]
    for name, value in (headers or {}).items():
        command += ["-H", f"{name}: {value}"]
    if data is not None:
        command += ["--data", data]
    command.append(url)
    output = subprocess.run(command, capture_output=True, text=True, check=False).stdout
    status, total, parsed = 0, 0.0, {}
    for line in output.splitlines():
        if line.startswith("HTTP/"):
            status = int(line.split()[1])
            parsed = {}  # keep the final response's headers only
        elif line.startswith("__total__="):
            total = float(line.split("=", 1)[1]) * 1000
        elif ":" in line:
            name, _, value = line.partition(":")
            parsed[name.strip().lower()] = value.strip()
    return Sample(status=status, total_ms=total, headers=parsed)


def summarise(values: list[float | None]) -> str:
    known = sorted(v for v in values if v is not None)
    if not known:
        return "n/a"
    p90 = known[min(len(known) - 1, round(0.9 * (len(known) - 1)))]
    return f"{statistics.median(known):.0f} / {p90:.0f} / {known[-1]:.0f}"


def row(name: str, samples: list[Sample]) -> str:
    statuses = ",".join(sorted({str(s.status) for s in samples}))
    columns = [
        summarise([s.upstream_ms for s in samples]),
        summarise([s.timing("app") for s in samples]),
        summarise([s.timing("db") for s in samples]),
        summarise([s.timing("db-connect") for s in samples]),
        summarise([s.timing("db-rt") for s in samples]),
        summarise([s.total_ms for s in samples]),
    ]
    return f"| {name} | {len(samples)} | {statuses} | " + " | ".join(columns) + " |"


TABLE_HEADER = (
    "| Request | n | Status | upstream ms | app ms | db ms | db-connect ms | db round trips "
    "| total ms (incl. observer distance) |\n|---|---|---|---|---|---|---|---|---|"
)


PROBE_CLINIC_NAME = "Performance probe (synthetic, no patients)"


def _post(url: str, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "30", "-w", "\n%{http_code}", *args, url],
        capture_output=True,
        text=True,
        check=False,
    )
    body, _, status = result.stdout.rpartition("\n")
    return (int(status) if status.isdigit() else 0), body


def sign_in(base_url: str) -> str | None:
    """Sign the probe account in, registering its probe clinic the first time it is used.

    The probe clinic is the only tenant this script ever touches. It is created through the public
    signup, exactly as a clinic would be, and holds no patients.
    """
    email, password = os.environ.get("PROBE_EMAIL"), os.environ.get("PROBE_PASSWORD")
    if not email or not password:
        return None
    login = (
        f"{base_url}{API}/login/access-token",
        "--data-urlencode",
        f"username={email}",
        "--data-urlencode",
        f"password={password}",
    )
    status, body = _post(*login)
    if status == 400:
        signup = json.dumps(
            {
                "email": email,
                "password": password,
                "full_name": "Performance probe",
                "clinic_name": PROBE_CLINIC_NAME,
            }
        )
        _post(
            f"{base_url}{API}/users/signup",
            "-H",
            "Content-Type: application/json",
            "--data",
            signup,
        )
        status, body = _post(*login)
    try:
        token = json.loads(body)["access_token"]
    except ValueError, KeyError:
        return None
    return token if isinstance(token, str) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    base, n = args.base_url.rstrip("/"), args.samples

    lines = [
        f"## Production timing: {base}",
        "",
        (
            f"Measured {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}. Cells are "
            "median / p90 / max. `upstream` and `Server-Timing` are measured at the origin and do not "
            "depend on where this runs; `total` includes the distance from this runner."
        ),
        "",
        TABLE_HEADER,
    ]

    # The first readiness call after an idle period pays for a suspended Neon compute, if any.
    first = fetch(f"{base}{API}/health/ready/")
    lines.append(row("readiness, first call", [first]))
    lines.append(
        row(
            "liveness (no database)",
            [fetch(f"{base}{API}/utils/health-check/") for _ in range(n)],
        )
    )
    lines.append(
        row(
            "readiness, sequential",
            [fetch(f"{base}{API}/health/ready/") for _ in range(n)],
        )
    )
    with ThreadPoolExecutor(max_workers=5) as pool:
        burst = list(pool.map(lambda _: fetch(f"{base}{API}/health/ready/"), range(n)))
    lines.append(row("readiness, 5 concurrent", burst))

    token = sign_in(base)
    if token:
        auth = {"Authorization": f"Bearer {token}"}
        week_start = time.strftime("%Y-%m-%d", time.gmtime())
        week_end = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400))
        reads = {
            "GET /users/me": f"{API}/users/me",
            "GET /users/me/permissions": f"{API}/users/me/permissions",
            "GET /dashboard/today": f"{API}/dashboard/today",
            "GET /patients": f"{API}/patients",
            "GET /tga-approvals": f"{API}/tga-approvals",
            "GET /prescriptions": f"{API}/prescriptions",
            "GET /appointments (one week)": f"{API}/appointments"
            f"?from={week_start}T00:00:00%2B10:00&to={week_end}T00:00:00%2B10:00",
            "GET /users/staff": f"{API}/users/staff",
        }
        for name, path in reads.items():
            lines.append(
                row(
                    name,
                    [
                        fetch(f"{base}{path}", headers=auth)
                        for _ in range(max(5, n // 4))
                    ],
                )
            )
    else:
        lines += [
            "",
            "_No probe account configured: authenticated reads not measured._",
        ]

    # Where the origin is: the response headers name the platform's edge and proxies, which is
    # evidence for the app's region when it cannot be read from the platform itself. Header names
    # and values only; nothing here is user data.
    probe = fetch(f"{base}{API}/utils/health-check/")
    lines += [
        "",
        "### Liveness response headers",
        "",
        "| Header | Value |",
        "|---|---|",
    ]
    for name in sorted(probe.headers):
        if name not in ("date", "content-length"):
            lines.append(f"| `{name}` | `{probe.headers[name]}` |")

    lines += [
        "",
        "### Static files",
        "",
        "| File | Status | cache-control | content-encoding |",
    ]
    lines.append("|---|---|---|---|")
    index = subprocess.run(
        ["curl", "-sS", "--max-time", "30", "-H", "Accept: text/html", f"{base}/"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    paths = ["/"] + sorted(
        set(re.findall(r"/assets/[A-Za-z0-9_.-]+\.(?:js|css|woff2)", index))
    )
    for path in paths:
        sample = fetch(
            f"{base}{path}",
            headers={
                "Accept": "text/html" if path == "/" else "*/*",
                "Accept-Encoding": "br, gzip",
            },
        )
        lines.append(
            f"| `{path}` | {sample.status} | {sample.headers.get('cache-control', '-')} "
            f"| {sample.headers.get('content-encoding', '-')} |"
        )

    report = "\n".join(lines) + "\n"
    sys.stdout.write(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
