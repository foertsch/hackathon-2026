#!/usr/bin/env python3
"""
Minimal client for the Sophia Genetics Variant Query Service (VQS).

Reads the bearer token from $IAM_TOKEN. Get a fresh token (1h TTL) at
https://iam-vandv.sophiagenetics.com/account/token while logged in.

Examples
--------
# Inspect the dataset key in plain JSON
./vqs_query.py decode-key "<base64 key>"

# Hit /schema for a known key
./vqs_query.py schema --key "<base64 key>"

# Run a query (body from a JSON file)
./vqs_query.py query \\
    --key "<base64 key>" \\
    --analysis-id 200042360 \\
    --interpretation-id interpretation-1042 \\
    --experiment-type-id 126000 \\
    --transformers FLATTEN,SHORT_SUBSET \\
    --body example_query.json

# Or pipe a body in
echo '{"columns":["*"],"pagination":{"limit":5}}' | \\
    ./vqs_query.py query --key "..." --analysis-id ... --body -

The default base URL is the hackathon instance and can be overridden with
$VQS_BASE_URL.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = os.environ.get(
    "VQS_BASE_URL", "https://platform-vandv1.sophiagenetics.com"
)


def _token() -> str:
    tok = os.environ.get("IAM_TOKEN", "").strip()
    if not tok:
        sys.exit("error: $IAM_TOKEN not set. Get one at https://iam-vandv.sophiagenetics.com/account/token")
    return tok


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _request(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def cmd_decode_key(args: argparse.Namespace) -> int:
    raw = base64.urlsafe_b64decode(args.key + "=" * (-len(args.key) % 4))
    print(json.dumps(json.loads(raw), indent=2))
    return 0


def _common_query(args: argparse.Namespace) -> str:
    # NB: the API uses bare keys (key, plan.parameters.X, plan.transformers),
    # not the "parameters."-prefixed form shown in some doc snippets.
    qs = {
        "key": args.key,
        "plan.parameters.analysisId": args.analysis_id,
        "plan.parameters.interpretationId": args.interpretation_id,
        "plan.parameters.experimentTypeId": args.experiment_type_id,
    }
    if args.transformers:
        qs["plan.transformers"] = args.transformers
    return urllib.parse.urlencode({k: v for k, v in qs.items() if v is not None})


def cmd_schema(args: argparse.Namespace) -> int:
    qs = _common_query(args)
    url = f"{args.base_url}/api/variant/query/schema?{qs}"
    status, body = _request("GET", url, headers=_headers())
    sys.stdout.buffer.write(body)
    print(f"\n# HTTP {status}", file=sys.stderr)
    return 0 if status == 200 else 1


def cmd_query(args: argparse.Namespace) -> int:
    if args.body == "-":
        body_text = sys.stdin.read()
    else:
        with open(args.body) as f:
            body_text = f.read()
    json.loads(body_text)  # validate

    qs = _common_query(args)
    url = f"{args.base_url}/api/variant/query?{qs}"
    status, body = _request(
        "POST",
        url,
        body=body_text.encode(),
        headers=_headers({"Content-Type": "application/json"}),
    )
    sys.stdout.buffer.write(body)
    print(f"\n# HTTP {status}", file=sys.stderr)
    return 0 if status == 200 else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Sophia Genetics VQS client")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    sub = p.add_subparsers(dest="cmd", required=True)

    sd = sub.add_parser("decode-key", help="Decode a base64 dataset key")
    sd.add_argument("key")
    sd.set_defaults(func=cmd_decode_key)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--key", required=True, help="Base64 dataset key")
    common.add_argument("--analysis-id", required=True)
    common.add_argument("--interpretation-id", required=True)
    common.add_argument("--experiment-type-id", default="126000")
    common.add_argument("--transformers", default=None,
                        help="Comma-separated transformers, e.g. FLATTEN,SHORT_SUBSET")

    ss = sub.add_parser("schema", help="GET /schema for a dataset", parents=[common])
    ss.set_defaults(func=cmd_schema)

    sq = sub.add_parser("query", help="POST a Query body", parents=[common])
    sq.add_argument("--body", required=True, help="Path to JSON body, or '-' for stdin")
    sq.set_defaults(func=cmd_query)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
