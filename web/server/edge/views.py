import json
import logging
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError
from .contracts import SyncRequest
from .ingestion import IngestError, ingest, token_digest
from .models import Gateway

logger = logging.getLogger(__name__)
BODY_LIMIT = 8 * 1024 * 1024


def failure(status, code, message):
    response = JsonResponse(
        {"detail": {"code": code, "message": message}}, status=status
    )
    if status == 401:
        response["WWW-Authenticate"] = "Bearer"
    return response


def unique_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Duplicate JSON key")
        data[key] = value
    return data


@csrf_exempt
def sync(request):
    if request.method != "POST":
        return failure(405, "method_not_allowed", "Use POST")
    authorization = request.headers.get("Authorization", "").split()
    if (
        len(authorization) != 2
        or authorization[0].lower() != "bearer"
        or not 32 <= len(authorization[1]) <= 512
        or not authorization[1].isascii()
    ):
        return failure(401, "invalid_token", "A registered Pi bearer token is required")
    digest = token_digest(authorization[1])
    try:
        if not Gateway.objects.filter(token_digest=digest, active=True).exists():
            return failure(
                401, "invalid_token", "A registered Pi bearer token is required"
            )
        if request.content_type != "application/json":
            return failure(
                422, "invalid_payload", "Content-Type must be application/json"
            )
        body = request.read(BODY_LIMIT + 1)
        if len(body) > BODY_LIMIT:
            return failure(413, "body_too_large", "Maximum request size is 8 MiB")
        batch = SyncRequest.model_validate(
            json.loads(body, object_pairs_hook=unique_keys)
        )
        return JsonResponse(ingest(batch, digest))
    except RequestDataTooBig:
        return failure(413, "body_too_large", "Maximum request size is 8 MiB")
    except (ValidationError, ValueError, UnicodeDecodeError):
        return failure(422, "invalid_payload", "Payload does not match edge schema v1")
    except IngestError as error:
        return failure(error.status, error.code, error.message)
    except DatabaseError:
        logger.exception("Edge transaction failed; no acknowledgement issued")
        return failure(
            503,
            "storage_unavailable",
            "Batch was not acknowledged; retry with the same event IDs",
        )


def health(request):
    if request.method != "GET":
        return failure(405, "method_not_allowed", "Use GET")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except DatabaseError:
        return failure(503, "storage_unavailable", "Storage unavailable")


def unknown(request, **kwargs):
    return failure(404, "not_found", "Unknown API route")
