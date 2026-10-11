# Pyright's aioboto3 stubs model get_credentials as synchronous, but the runtime
# method is awaitable. Remove this override when upstream typing is corrected.
# pyright: reportGeneralTypeIssues=false
"""
SigV4 signing for OpenAI-compatible Amazon Bedrock HTTP requests.

Lives in its own module so the Mantle registry and the shared Responses client
can import it at module
level without creating a cycle between them.
"""

from typing import Dict, Optional

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from app.core.config import get_settings


async def signed_headers(
    method: str,
    url: str,
    body_bytes: bytes,
    region: str,
    service: Optional[str] = None,
) -> Dict[str, str]:
    """Return SigV4-signed headers for a Bedrock HTTP request.

    Credentials come from the shared BedrockClient aioboto3 session (reuses the
    EKS Pod IRSA/STS chain, including a SessionToken → ``X-Amz-Security-Token``).
    In aiobotocore both ``get_credentials`` and ``get_frozen_credentials`` are
    coroutines and must be awaited (unlike sync botocore).

    The signature is computed over the EXACT *body_bytes* that will be sent.
    """
    from app.services.bedrock import BedrockClient

    session = BedrockClient.get_instance().session
    creds = await session.get_credentials()
    if creds is None:
        raise RuntimeError("No AWS credentials available to sign Bedrock request")
    frozen = await creds.get_frozen_credentials()

    signing_service = service or get_settings().MANTLE_SIGV4_SERVICE
    aws_req = AWSRequest(
        method=method,
        url=url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(frozen, signing_service, region).add_auth(aws_req)
    return dict(aws_req.headers)
