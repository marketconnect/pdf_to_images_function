import base64
import json
import logging
import os
import uuid
from io import BytesIO
from typing import Any, Dict, Tuple

import boto3
from botocore.exceptions import ClientError
from PIL import Image
import pypdfium2 as pdfium


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_s3_client():
    endpoint_url = os.environ.get("S3_ENDPOINT_URL")
    region_name = os.environ.get("AWS_REGION")
    # Credentials are taken from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars by boto3 automatically
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
    )

def get_bucket_name() -> str:
    bucket = os.environ.get("S3_BUCKET_NAME")
    if not bucket:
        raise BadRequest("Environment variable 'S3_BUCKET_NAME' is not set.")
    return bucket


S3_CLIENT = get_s3_client()
BUCKET_NAME = get_bucket_name()

class BadRequest(Exception):
    pass


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False),
    }


def parse_event(event: Dict[str, Any]) -> Tuple[str, str]:
    """
    Parse input event for pdf_key and output_prefix.
    Accepts:
      - Direct dict payload with keys
      - HTTP-style event with JSON in 'body' (optionally base64 encoded)
    """
    if not isinstance(event, dict):
        raise BadRequest("Invalid event type; expected JSON object.")

    payload = None

    # Direct invocation with keys at top-level
    if "pdf_key" in event and "output_prefix" in event:
        payload = event
    # HTTP-style event with body
    elif "body" in event:
        body = event.get("body")
        if body is None:
            raise BadRequest("Empty body in event.")
        if event.get("isBase64Encoded") is True:
            try:
                body = base64.b64decode(body).decode("utf-8")
            except Exception:
                raise BadRequest("Failed to decode base64-encoded body.")
        if isinstance(body, (bytes, bytearray)):
            try:
                body = body.decode("utf-8")
            except Exception:
                raise BadRequest("Request body must be UTF-8 text.")
        if not isinstance(body, str):
            raise BadRequest("Request body must be a string containing JSON.")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise BadRequest("Request body is not valid JSON.")
    else:
        raise BadRequest("Missing required fields. Provide 'pdf_key' and 'output_prefix'.")

    pdf_key = payload.get("pdf_key")
    output_prefix = payload.get("output_prefix")

    if not isinstance(pdf_key, str) or not pdf_key:
        raise BadRequest("Field 'pdf_key' must be a non-empty string.")
    if not isinstance(output_prefix, str) or not output_prefix:
        raise BadRequest("Field 'output_prefix' must be a non-empty string.")
    if not output_prefix.endswith("/"):
        raise BadRequest("Field 'output_prefix' must end with '/'.")

    return pdf_key, output_prefix







def download_pdf_to_tmp(s3_client, bucket: str, pdf_key: str) -> str:
    tmp_filename = f"{uuid.uuid4().hex}.pdf"
    tmp_path = os.path.join("/tmp", tmp_filename)
    logger.info("Downloading PDF from s3://%s/%s to %s", bucket, pdf_key, tmp_path)
    try:
        s3_client.download_file(bucket, pdf_key, tmp_path)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("NoSuchKey", "404", "NotFound"):
            raise FileNotFoundError(f"Object not found: s3://{bucket}/{pdf_key}") from e
        raise
    return tmp_path


def upload_bytes(s3_client, bucket: str, key: str, data: bytes, content_type: str):
    logger.info("Uploading to s3://%s/%s (%s)", bucket, key, content_type)
    s3_client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def convert_pdf_pages_to_webp_and_upload(
    s3_client, bucket: str, local_pdf_path: str, output_prefix: str, dpi: int = 150, quality: int = 85
) -> int:
    """
        Convert PDF pages to WebP and upload each page as {output_prefix}page-{i}.webp, 1-based indexing.
        Skips pages that already exist in the destination.
        Returns the total number of pages in the PDF.
    """
    
    logger.info("Opening PDF via pypdfium2: %s", local_pdf_path)
    doc = pdfium.PdfDocument(local_pdf_path)
    try:
        page_count = len(doc)
        logger.info("PDF has %d pages", page_count)
        # Find pages that already exist in S3 to avoid re-processing.
        existing_pages = set()
        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=output_prefix):
                for obj in page.get("Contents", []):
                    key = obj.get("Key")
                    if not key:
                        continue
                    # Extract 'page-N.webp' from '.../page-N.webp'
                    filename = key.split("/")[-1]
                    if filename.startswith("page-") and filename.endswith(".webp"):
                        try:
                            page_num_str = filename[len("page-") : -len(".webp")]
                            existing_pages.add(int(page_num_str))
                        except (ValueError, TypeError):
                            logger.warning("Could not parse page number from S3 key: %s", key)
        except ClientError as e:
            logger.error("Failed to list existing pages in S3 for prefix '%s': %s", output_prefix, e)
            raise  # Propagate the error to the main handler
        logger.info("Found %d existing pages in S3. Will skip them.", len(existing_pages))
        # Scale factor based on DPI relative to PDF's 72 DPI reference
        scale = dpi / 72.0
        
        for i in range(page_count):
            page_num = i + 1
            if page_num in existing_pages:
                logger.info("Skipping page %d/%d (already exists)", page_num, page_count)
                continue
            logger.info("Rendering page %d/%d", page_num, page_count)
            
            page = doc[i]
            try:
                bitmap = page.render(scale=scale)
                pil_img: Image.Image = bitmap.to_pil()
                buf = BytesIO()
                pil_img.save(buf, format="WEBP", quality=quality, method=6)
                buf.seek(0)

                key = f"{output_prefix}page-{page_num}.webp"
                upload_bytes(s3_client, bucket, key, buf.getvalue(), "image/webp")
            finally:
                # Explicitly close page resources
                try:
                    page.close()
                except Exception:
                    pass
        return page_count
    finally:
        try:
            doc.close()
        except Exception:
            pass


def upload_manifest(s3_client, bucket: str, output_prefix: str, page_count: int):
    manifest_key = f"{output_prefix}manifest.json"
    manifest_obj = {"page_count": page_count, "format": "webp"}
    data = json.dumps(manifest_obj, ensure_ascii=False).encode("utf-8")
    upload_bytes(s3_client, bucket, manifest_key, data, "application/json")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("PdfToImagesFunction invoked")
    tmp_pdf_path = None
    try:
        pdf_key, output_prefix = parse_event(event)
        bucket = get_bucket_name()
        s3_client = get_s3_client()

        tmp_pdf_path = download_pdf_to_tmp(s3_client, bucket, pdf_key)

        page_count = convert_pdf_pages_to_webp_and_upload(
            s3_client, bucket, tmp_pdf_path, output_prefix, dpi=150, quality=85
        )

        upload_manifest(s3_client, bucket, output_prefix, page_count)

        success_payload = {
            "status": "success",
            "page_count": page_count,
            "format": "webp",
        }
        logger.info("Conversion completed successfully: %s pages", page_count)
        return json_response(200, success_payload)

    except BadRequest as e:
        logger.warning("Bad request: %s", e)
        return json_response(400, {"status": "error", "message": str(e)})
    except FileNotFoundError as e:
        logger.warning("File not found: %s", e)
        # Return 404 for missing source object
        return json_response(404, {"status": "error", "message": str(e)})
    except ClientError as e:
        logger.exception("S3 client error")
        return json_response(500, {"status": "error", "message": f"S3 error: {str(e)}"})
    except Exception as e:
        logger.exception("Unhandled error during conversion")
        return json_response(500, {"status": "error", "message": str(e)})
    finally:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            try:
                os.remove(tmp_pdf_path)
                logger.info("Removed temporary file: %s", tmp_pdf_path)
            except Exception:
                logger.warning("Failed to remove temporary file: %s", tmp_pdf_path)
