"""Field types shared by the gateway request schemas."""

from typing import Annotated

from pydantic import StringConstraints

# Every Bedrock, Mantle and Gemini model ID (and inference profile ARN) is
# printable ASCII without spaces. The value is logged and used as a metric
# label before entitlement checks run, so reject anything else up front:
# CR/LF and escape sequences would otherwise land verbatim in operator logs.
ModelId = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=r"^[!-~]+$")
]
