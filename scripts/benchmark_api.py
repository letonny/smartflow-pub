"""Reproducible local HTTP round-trip sample; not a capacity certification."""
import argparse
import asyncio
import json
import platform
import statistics
import time

import httpx


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 2)


async def run(base_url, path, requests, concurrency):
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=10, limits=limits) as client:
        health = await client.get("/api/health")
        health.raise_for_status()
        mode = health.json().get("mode", "UNKNOWN")
        for _ in range(5):
            response = await client.get(path)
            response.raise_for_status()
        semaphore = asyncio.Semaphore(concurrency)
        samples = []
        errors = 0

        async def one():
            nonlocal errors
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(path)
                    response.raise_for_status()
                    samples.append((time.perf_counter() - started) * 1000)
                except (httpx.HTTPError, ValueError):
                    errors += 1

        started = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(requests)))
        wall_seconds = time.perf_counter() - started
        return {
            "mode": mode, "requests": requests,
            "concurrency": concurrency, "successes": len(samples), "errors": errors,
            "wall_seconds": round(wall_seconds, 3),
            "successful_requests_per_second": round(len(samples) / wall_seconds, 2),
            "p50_ms": percentile(samples, .5) if samples else None,
            "p95_ms": percentile(samples, .95) if samples else None,
            "mean_ms": round(statistics.mean(samples), 2) if samples else None,
            "platform": platform.platform(), "python": platform.python_version(),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--path", default="/api/dashboard")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or not args.path.startswith("/"):
        parser.error("requests and concurrency must be positive; path must start with /")
    try:
        result = asyncio.run(run(args.base_url, args.path, args.requests, args.concurrency))
    except (httpx.HTTPError, ValueError) as exc:
        parser.exit(1, f"Benchmark request failed ({type(exc).__name__}).\n")
    print(json.dumps(result, indent=2))
