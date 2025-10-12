import os
import sys
import json
import argparse
import base64

# Ensure project root is on sys.path to import src.handler
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from handler import handler as fn_handler  # noqa: E402


def build_event(pdf_key: str, output_prefix: str, http_event: bool, use_base64: bool) -> dict:
    if not http_event:
        return {
            "pdf_key": pdf_key,
            "output_prefix": output_prefix,
        }

    body = json.dumps({"pdf_key": pdf_key, "output_prefix": output_prefix}, ensure_ascii=False)
    if use_base64:
        body = base64.b64encode(body.encode("utf-8")).decode("utf-8")
    return {
        "body": body,
        "isBase64Encoded": use_base64,
    }


def main():
    parser = argparse.ArgumentParser(description="Local invoke for PdfToImagesFunction")
    parser.add_argument("--pdf-key", required=True, help="S3 key of source PDF (e.g., path/to/document.pdf)")
    parser.add_argument(
        "--output-prefix", required=True, help="Output prefix ending with '/' (e.g., converted/path/to/document.xlsx/)"
    )
    parser.add_argument("--http-event", action="store_true", help="Wrap payload as HTTP-style event with body")
    parser.add_argument("--base64", action="store_true", help="Base64-encode the HTTP body (only with --http-event)")
    args = parser.parse_args()

    if args.base64 and not args.http_event:
        parser.error("--base64 requires --http-event")

    event = build_event(args.pdf_key, args.output_prefix, args.http_event, args.base64)

    print("Invoking handler with event:")
    print(json.dumps(event, ensure_ascii=False, indent=2))

    resp = fn_handler(event, None)

    print("\nResponse:")
    # Pretty print JSON body if possible
    body = resp.get("body")
    try:
        parsed_body = json.loads(body) if isinstance(body, str) else body
    except Exception:
        parsed_body = body

    pretty = dict(resp)
    pretty["body"] = parsed_body
    print(json.dumps(pretty, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
