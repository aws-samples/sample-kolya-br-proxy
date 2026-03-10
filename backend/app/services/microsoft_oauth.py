"""Microsoft OAuth service for authentication."""

import logging
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MicrosoftOAuthService:
    """Service for Microsoft OAuth authentication."""

    def __init__(self):
        self.settings = get_settings()
        self.client_id = self.settings.MICROSOFT_CLIENT_ID
        self.client_secret = self.settings.MICROSOFT_CLIENT_SECRET
        self.tenant_id = self.settings.MICROSOFT_TENANT_ID or "common"
        self.allowed_redirect_uris = self.settings.get_microsoft_redirect_uris()

        # Microsoft OAuth endpoints
        self.authorize_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        )
        self.token_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )
        self.user_info_url = "https://graph.microsoft.com/v1.0/me"

    def is_configured(self) -> bool:
        """Check if Microsoft OAuth is configured."""
        return bool(self.client_id and self.client_secret)

    def _validate_redirect_uri(self, redirect_uri: str) -> None:
        """
        Validate that redirect_uri is in the allowed list.

        Args:
            redirect_uri: Redirect URI to validate

        Raises:
            HTTPException: If redirect_uri is not allowed
        """
        if not self.allowed_redirect_uris:
            logger.warning(
                "No allowed redirect URIs configured for Microsoft OAuth. "
                "Set KBR_MICROSOFT_REDIRECT_URIS environment variable."
            )
            return

        if redirect_uri not in self.allowed_redirect_uris:
            logger.warning(
                f"Invalid redirect_uri attempted: {redirect_uri}. "
                f"Allowed URIs: {self.allowed_redirect_uris}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid redirect_uri. Must be one of: {', '.join(self.allowed_redirect_uris)}",
            )

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """
        Get Microsoft OAuth authorization URL.

        Args:
            redirect_uri: Redirect URI after authorization
            state: State parameter for CSRF protection

        Returns:
            Authorization URL
        """
        if not self.is_configured():
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Microsoft OAuth not configured",
            )

        # Validate redirect_uri
        self._validate_redirect_uri(redirect_uri)

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email User.Read",
            "state": state,
        }

        query_string = urlencode(params)
        return f"{self.authorize_url}?{query_string}"

    async def exchange_code_for_token(
        self, code: str, redirect_uri: str
    ) -> dict[str, str]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from Microsoft
            redirect_uri: Redirect URI used in authorization

        Returns:
            Token response with access_token, id_token, etc.
        """
        if not self.is_configured():
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Microsoft OAuth not configured",
            )

        # Validate redirect_uri
        self._validate_redirect_uri(redirect_uri)

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.token_url, data=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to exchange code for token: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code",
                )

    async def get_user_info(self, access_token: str) -> dict[str, str]:
        """
        Get user information from Microsoft Graph API.

        Args:
            access_token: Microsoft access token

        Returns:
            User information including id, email, name, etc.
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.user_info_url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get user info: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get user information",
                )


def get_microsoft_oauth_service() -> MicrosoftOAuthService:
    """Get Microsoft OAuth service instance."""
    return MicrosoftOAuthService()
