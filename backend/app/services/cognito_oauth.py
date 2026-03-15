"""AWS Cognito OAuth service for authentication."""

import base64
import hashlib
import hmac
import logging
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CognitoOAuthService:
    """Service for AWS Cognito OAuth authentication."""

    def __init__(self):
        self.settings = get_settings()
        self.user_pool_id = self.settings.COGNITO_USER_POOL_ID
        self.client_id = self.settings.COGNITO_CLIENT_ID
        self.client_secret = self.settings.COGNITO_CLIENT_SECRET
        self.region = self.settings.COGNITO_REGION or self.settings.AWS_REGION
        self.allowed_redirect_uris = self.settings.get_cognito_redirect_uris()

        # Determine Cognito domain
        if self.settings.COGNITO_DOMAIN:
            # Use explicitly configured domain
            self.cognito_domain = f"https://{self.settings.COGNITO_DOMAIN}.auth.{self.region}.amazoncognito.com"
        elif self.user_pool_id:
            # Fallback: Extract domain from user pool ID (format: {region}_{id})
            # This is less reliable and should be avoided
            pool_parts = self.user_pool_id.split("_")
            if len(pool_parts) >= 2:
                # Cognito domain format: https://{domain}.auth.{region}.amazoncognito.com
                self.cognito_domain = f"https://{pool_parts[1].lower()}.auth.{self.region}.amazoncognito.com"
                logger.warning(
                    f"Using auto-extracted Cognito domain: {self.cognito_domain}. "
                    "Consider setting KBR_COGNITO_DOMAIN explicitly."
                )
            else:
                self.cognito_domain = None
        else:
            self.cognito_domain = None

        # Cognito OAuth endpoints
        if self.cognito_domain:
            self.authorize_url = f"{self.cognito_domain}/oauth2/authorize"
            self.token_url = f"{self.cognito_domain}/oauth2/token"
            self.user_info_url = f"{self.cognito_domain}/oauth2/userInfo"
        else:
            self.authorize_url = None
            self.token_url = None
            self.user_info_url = None

    def is_configured(self) -> bool:
        """Check if Cognito OAuth is configured."""
        return bool(
            self.user_pool_id
            and self.client_id
            and self.client_secret
            and self.cognito_domain
        )

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
                "No allowed redirect URIs configured for Cognito OAuth. "
                "Set KBR_COGNITO_REDIRECT_URIS environment variable."
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

    def _get_secret_hash(self, username: str) -> str:
        """
        Calculate SECRET_HASH for Cognito API calls.

        AWS Cognito requires a SECRET_HASH when the app client has a secret.
        The hash is computed as: Base64(HMAC_SHA256(client_secret, username + client_id))

        Args:
            username: Username or email

        Returns:
            Base64-encoded SECRET_HASH
        """
        message = username + self.client_id
        dig = hmac.new(
            self.client_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(dig).decode()

    def get_authorization_url(
        self, redirect_uri: str, state: str, code_challenge: str | None = None
    ) -> str:
        """
        Get Cognito OAuth authorization URL.

        Args:
            redirect_uri: Redirect URI after authorization
            state: State parameter for CSRF protection
            code_challenge: PKCE code challenge (S256)

        Returns:
            Authorization URL
        """
        if not self.is_configured():
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Cognito OAuth not configured",
            )

        # Validate redirect_uri
        self._validate_redirect_uri(redirect_uri)

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
        }

        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        query_string = urlencode(params)
        return f"{self.authorize_url}?{query_string}"

    async def exchange_code_for_token(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, str]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from Cognito
            redirect_uri: Redirect URI used in authorization
            code_verifier: PKCE code verifier

        Returns:
            Token response with access_token, id_token, refresh_token, etc.
        """
        if not self.is_configured():
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Cognito OAuth not configured",
            )

        # Validate redirect_uri
        self._validate_redirect_uri(redirect_uri)

        # Cognito token endpoint requires Basic Auth with client_id:client_secret
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}",
        }

        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.token_url, headers=headers, data=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to exchange code for token: {e}")
                logger.error(f"Response: {e.response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code",
                )

    async def get_user_info(self, access_token: str) -> dict[str, str]:
        """
        Get user information from Cognito.

        Args:
            access_token: Cognito access token

        Returns:
            User information including sub (user ID), email, name, etc.
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


def get_cognito_oauth_service() -> CognitoOAuthService:
    """Get Cognito OAuth service instance."""
    return CognitoOAuthService()
