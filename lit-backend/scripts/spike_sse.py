"""
Client half of the streaming spike: measure whether SSE arrives in real time through a proxy.

    python scripts/spike_sse.py https://<space>.hf.space --seconds 150
    python scripts/spike_sse.py https://<space>.hf.space --seconds 120 --silent-from 20 --silent-for 50   # idle-limit probe
    python scripts/spike_sse.py https://<space>.hf.space --cors https://lit-ngin.vercel.app             # preflight only

Prints per-event lag (client arrival time minus the server's own elapsed time, relative to the first event) and a
verdict. Buffering shows up as events arriving in bursts; an idle timeout shows up as the stream dying mid-silence.
"""

import argparse
import json
import sys
import time

import httpx


def _auth_headers(enabled: bool) -> dict:
    """Private Spaces need the owner's HF token; it is read from the local login and never printed."""
    if not enabled:
        return {}
    from huggingface_hub import get_token
    token = get_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def cors_check(base: str, origin: str, auth: bool = False) -> bool:
    url = f"{base}/api/v1/agent/schema"
    pre = httpx.options(url, headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-client-version,last-event-id",
        **_auth_headers(auth),
    }, timeout=30)
    allow_origin = pre.headers.get("access-control-allow-origin")
    allow_headers = pre.headers.get("access-control-allow-headers", "")
    print(f"preflight {pre.status_code}: allow-origin={allow_origin!r} allow-headers={allow_headers!r}")
    return pre.status_code in (200, 204) and allow_origin in (origin, "*")


def run_stream(base: str, params: dict, origin: str | None, auth: bool = False) -> bool:
    headers = {"Accept": "text/event-stream", **_auth_headers(auth)}
    if origin:
        headers["Origin"] = origin
    t0 = time.monotonic()
    first_arrival = None
    first_server_t = None
    max_gap = 0.0
    last_arrival = None
    lags = []
    events = 0
    ended = "stream closed without 'done'"
    with httpx.Client(timeout=httpx.Timeout(10, read=params["seconds"] + 60)) as client:
        with client.stream("GET", f"{base}/api/v1/spike/stream", params=params, headers=headers) as resp:
            print(f"HTTP {resp.status_code}  content-type={resp.headers.get('content-type')}  "
                  f"content-encoding={resp.headers.get('content-encoding')}  "
                  f"cors={resp.headers.get('access-control-allow-origin')!r}")
            if resp.status_code != 200:
                print(resp.read().decode()[:300])
                return False
            event = None
            for line in resp.iter_lines():
                now = time.monotonic() - t0
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    data = json.loads(line[5:])
                    events += 1
                    if first_arrival is None:
                        first_arrival, first_server_t = now, data.get("t", 0) / 1000
                    server_t = data.get("t", 0) / 1000
                    lag = (now - first_arrival) - (server_t - first_server_t)
                    lags.append(lag)
                    if last_arrival is not None:
                        max_gap = max(max_gap, now - last_arrival)
                    last_arrival = now
                    if event != "hello":
                        print(f"  {now:7.2f}s  {event:5s} server_t={server_t:7.2f}s  lag={lag:+.2f}s")
                    if event == "done":
                        ended = "done received"
    print(f"events={events}  max_gap_between_events={max_gap:.1f}s  worst_lag={max(lags):+.2f}s  end: {ended}")
    return ended == "done received" and max(lags) < 2.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--tick", type=int, default=5)
    ap.add_argument("--ping", type=int, default=10)
    ap.add_argument("--silent-from", type=int, default=0)
    ap.add_argument("--silent-for", type=int, default=0)
    ap.add_argument("--origin", default=None, help="send this Origin header on the stream request")
    ap.add_argument("--cors", default=None, help="run only a CORS preflight check for this origin")
    ap.add_argument("--hf-auth", action="store_true", help="send the local HF token (needed for private Spaces)")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    if args.cors:
        sys.exit(0 if cors_check(base, args.cors, args.hf_auth) else 1)
    ok = run_stream(base, dict(seconds=args.seconds, tick=args.tick, ping=args.ping,
                               silent_from=args.silent_from, silent_for=args.silent_for), args.origin, args.hf_auth)
    print("VERDICT:", "real-time, survived" if ok else "PROBLEM (buffered, delayed, or cut)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
