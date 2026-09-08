"""Measures the performance NFR against a running server.

    python -m scripts.loadtest --users 20 --rounds 5

Targets from the BRD:
  * 95% of standard page and API actions within 3 seconds
  * response auto-save within 2 seconds
  * final report generation for a full assessment within 5 minutes

Prints the measured p50/p95/p99 per endpoint and a pass/fail against each
target, so the number in the acceptance pack is measured rather than asserted.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8010/api/v1"
PASSWORD = "Remas#2026"

TARGETS = {"standard": 3.0, "autosave": 2.0, "report": 300.0}


def call(method: str, path: str, body=None, token: str | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, data, timeout=310) as res:
            res.read()
            return time.perf_counter() - started, res.status
    except urllib.error.HTTPError as exc:
        exc.read()
        return time.perf_counter() - started, exc.code


def login(email: str) -> str:
    _, _ = call("POST", "/auth/login", {"email": email, "password": PASSWORD})
    req = urllib.request.Request(BASE + "/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    payload = json.dumps({"email": email, "password": PASSWORD}).encode()
    with urllib.request.urlopen(req, payload, timeout=30) as res:
        return json.loads(res.read().decode())["access_token"]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * pct), len(ordered) - 1)]


def report(name: str, samples: list[float], target: float) -> bool:
    if not samples:
        print(f"  {name:<34} no samples")
        return False
    p95 = percentile(samples, 0.95)
    verdict = "PASS" if p95 <= target else "FAIL"
    print(
        f"  {verdict}  {name:<30} n={len(samples):<5} "
        f"p50={percentile(samples, 0.5):.3f}s  p95={p95:.3f}s  "
        f"p99={percentile(samples, 0.99):.3f}s  max={max(samples):.3f}s  "
        f"(target {target}s)"
    )
    return p95 <= target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=10, help="concurrent workers")
    parser.add_argument("--rounds", type=int, default=5, help="iterations per worker")
    args = parser.parse_args()

    token = login("owner@demodeveloper.com")
    framework = json.loads(
        urllib.request.urlopen(
            _authed("/frameworks/current", token), timeout=60
        ).read().decode()
    )
    axes = framework["axes"][:3]
    questions = [q for a in axes for q in a["questions"]]

    created = _post_json(
        "/assessments",
        {
            "name": "load test",
            "layer": "ai_report",
            "selected_axis_ids": [a["id"] for a in axes],
        },
        token,
    )
    assessment_id = created["id"]

    standard: list[float] = []
    autosave: list[float] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        local_standard: list[float] = []
        local_autosave: list[float] = []
        for _ in range(args.rounds):
            for path in (
                "/frameworks/current?with_questions=false",
                "/assessments",
                f"/assessments/{assessment_id}",
                f"/assessments/{assessment_id}/progress",
                f"/assessments/{assessment_id}/questions",
                "/catalogue/preview",
                "/documents",
            ):
                elapsed, _ = call("GET", path, token=token)
                local_standard.append(elapsed)

            question = questions[index % len(questions)]
            elapsed, _ = call(
                "PUT",
                f"/assessments/{assessment_id}/responses",
                [{"question_id": question["id"], "score": (index % 5) + 1}],
                token,
            )
            local_autosave.append(elapsed)

        with lock:
            standard.extend(local_standard)
            autosave.extend(local_autosave)

    print(f"\nrunning {args.users} workers x {args.rounds} rounds…")
    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.users)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - started

    # Answer everything, submit, then time a real report render.
    _put_json(
        f"/assessments/{assessment_id}/responses",
        [{"question_id": q["id"], "score": (i % 5) + 1} for i, q in enumerate(questions)],
        token,
    )
    call("POST", f"/assessments/{assessment_id}/submit", token=token)
    call("POST", f"/assessments/{assessment_id}/ai/run",
         {"stages": ["analyse", "recommend"]}, token)
    report_time, status_code = call("GET", f"/assessments/{assessment_id}/report.pdf?locale=ar", token=token)

    total = len(standard) + len(autosave)
    print(f"\n{total} requests in {wall:.1f}s  ({total / wall:.0f} req/s)\n")
    results = [
        report("standard page/API actions", standard, TARGETS["standard"]),
        report("response auto-save", autosave, TARGETS["autosave"]),
        report("final report (PDF)", [report_time], TARGETS["report"]),
    ]
    print(f"\n  report HTTP status: {status_code}")
    print(f"\n  mean standard latency: {statistics.mean(standard):.3f}s")
    print("\nRESULT:", "ALL TARGETS MET" if all(results) else "TARGET MISSED")
    raise SystemExit(0 if all(results) else 1)


def _authed(path: str, token: str) -> urllib.request.Request:
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", "Bearer " + token)
    return req


def _post_json(path: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(BASE + path, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, json.dumps(body).encode(), timeout=60) as res:
        return json.loads(res.read().decode())


def _put_json(path: str, body: list, token: str) -> None:
    req = urllib.request.Request(BASE + path, method="PUT")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, json.dumps(body).encode(), timeout=120) as res:
            res.read()
    except urllib.error.HTTPError as exc:
        exc.read()


if __name__ == "__main__":
    main()
