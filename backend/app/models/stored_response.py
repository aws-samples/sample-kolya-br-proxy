"""Which API key created each stored upstream response.

Bedrock stores Responses API results (``store`` defaults to true) per AWS
account, and every key shares the gateway's account. ``previous_response_id``
continues a stored response - context included - for whoever presents the
ID, so the gateway records the owner and only lets that key continue it.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base


class StoredResponse(Base):
    __tablename__ = "stored_responses"

    response_id = Column(String(128), primary_key=True)
    token_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
