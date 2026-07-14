"""
SigV4 signing for AWS mantle (OpenAI-on-Bedrock) HTTP requests.

Lives in its own module so both the registry (``mantle_models``, discovery
probes) and the inference client (``mantle_client``) can import it at module
level without creating a cycle between them.
"""

from typing import Dict

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from app.core.config import get_settings


async def signed_headers(
    method: str, url: str, body_bytes: bytes, region: str
) -> Dict[str, str]:
    """Return SigV4-signed headers for a mantle request.

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
        raise RuntimeError("No AWS credentials available to sign mantle request")
    frozen = await creds.get_frozen_credentials()

    service = get_settings().MANTLE_SIGV4_SERVICE
    aws_req = AWSRequest(
        method=method,
        url=url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(frozen, service, region).add_auth(aws_req)
    return dict(aws_req.headers)
