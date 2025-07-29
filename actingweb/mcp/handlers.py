"""
Bridge handlers between ActingWeb and MCP.

This module provides utility functions to help bridge ActingWeb's hook system
with MCP functionality, handling data transformation and context management.
"""

from typing import Any, Dict, Optional, List
import logging

from ..interface.actor_interface import ActorInterface


logger = logging.getLogger(__name__)


class MCPActorContext:
    """
    Context object that provides ActingWeb actor information to MCP handlers.
    
    This allows MCP tools, resources, and prompts to access the current
    ActingWeb actor and its properties.
    """
    
    def __init__(self, actor: ActorInterface) -> None:
        self.actor = actor
        self.actor_id = actor.id
        
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get an actor property value."""
        try:
            return self.actor.properties.get(key, default)
        except Exception as e:
            logger.error(f"Error getting property {key}: {e}")
            return default
            
    def set_property(self, key: str, value: Any) -> bool:
        """Set an actor property value."""
        try:
            self.actor.properties[key] = value
            return True
        except Exception as e:
            logger.error(f"Error setting property {key}: {e}")
            return False


def validate_mcp_parameters(params: Dict[str, Any], required_params: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Validate and normalize MCP parameters for ActingWeb consumption.
    
    Args:
        params: Parameters from MCP request
        required_params: List of required parameter names
        
    Returns:
        Validated and normalized parameters
        
    Raises:
        ValueError: If required parameters are missing
    """
    if required_params:
        missing = [param for param in required_params if param not in params]
        if missing:
            raise ValueError(f"Missing required parameters: {', '.join(missing)}")
    
    # Normalize parameter values
    normalized = {}
    for key, value in params.items():
        # Convert None to empty string for consistency
        if value is None:
            normalized[key] = ""
        else:
            normalized[key] = value
            
    return normalized


def format_mcp_response(result: Any, success: bool = True) -> Dict[str, Any]:
    """
    Format ActingWeb results for MCP consumption.
    
    Args:
        result: Result from ActingWeb hook execution
        success: Whether the operation was successful
        
    Returns:
        Formatted response for MCP
    """
    response: Dict[str, Any] = {
        "success": success,
        "timestamp": None  # Could add timestamp if needed
    }
    
    if success:
        if isinstance(result, dict):
            response.update(result)
        else:
            response["result"] = result
    else:
        response["error"] = str(result) if result else "Unknown error"
        
    return response


def extract_email_from_oauth_token(bearer_token: str) -> Optional[str]:
    """
    Extract email from Google OAuth2 Bearer token.
    
    This function validates the Bearer token with Google's APIs and retrieves
    the user's email address.
    
    Args:
        bearer_token: OAuth2 access token from Google (without "Bearer " prefix)
        
    Returns:
        Email address from Google UserInfo API or None if invalid
    """
    if not bearer_token:
        return None
        
    try:
        # Phase 3 implementation will:
        # 1. Validate token with Google TokenInfo API
        # 2. Call Google UserInfo API to get user profile
        # 3. Extract and return email address
        
        # For now, mock implementation
        if bearer_token.startswith("mock_google_oauth_token"):
            return "user@gmail.com"
            
        # Real implementation will look like:
        # 
        # import requests
        # 
        # # Validate token with Google
        # token_info_url = f"https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={bearer_token}"
        # token_response = requests.get(token_info_url, timeout=10)
        # 
        # if token_response.status_code != 200:
        #     logger.warning("Invalid Google OAuth token")
        #     return None
        # 
        # token_data = token_response.json()
        # 
        # # Verify the token is for our application
        # if token_data.get('audience') != GOOGLE_CLIENT_ID:
        #     logger.warning("Token not issued for this application")
        #     return None
        # 
        # # Get user info from Google
        # userinfo_url = f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={bearer_token}"
        # userinfo_response = requests.get(userinfo_url, timeout=10)
        # 
        # if userinfo_response.status_code != 200:
        #     logger.error("Failed to get user info from Google")
        #     return None
        # 
        # user_data = userinfo_response.json()
        # return user_data.get('email')
        
        return None
            
    except Exception as e:
        logger.error(f"Error extracting email from OAuth token: {e}")
        return None


def create_google_oauth_redirect_url(client_id: str, redirect_uri: str, state: Optional[str] = None) -> str:
    """
    Create Google OAuth2 authorization URL for MCP authentication.
    
    Args:
        client_id: Google OAuth client ID
        redirect_uri: Callback URI for OAuth redirect
        state: Optional state parameter for CSRF protection
        
    Returns:
        Complete Google OAuth authorization URL
    """
    import urllib.parse
    
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",  # We need email for actor lookup
        "response_type": "code",
        "access_type": "offline",  # Get refresh token
        "prompt": "consent"  # Always show consent screen
    }
    
    if state:
        params["state"] = state
    
    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"


def exchange_oauth_code_for_token(code: str, client_id: str, client_secret: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """
    Exchange OAuth authorization code for access token (placeholder for Phase 3).
    
    Args:
        code: Authorization code from Google OAuth callback
        client_id: Google OAuth client ID
        client_secret: Google OAuth client secret
        redirect_uri: The same redirect URI used in authorization request
        
    Returns:
        Token response with access_token, refresh_token, etc. or None if failed
    """
    # Phase 3 implementation will:
    # 1. POST to Google's token endpoint
    # 2. Exchange authorization code for access token
    # 3. Return token response
    
    # Real implementation will look like:
    #
    # import requests
    #
    # token_url = "https://oauth2.googleapis.com/token"
    # 
    # data = {
    #     "code": code,
    #     "client_id": client_id,
    #     "client_secret": client_secret,
    #     "redirect_uri": redirect_uri,
    #     "grant_type": "authorization_code"
    # }
    # 
    # response = requests.post(token_url, data=data, timeout=10)
    # 
    # if response.status_code == 200:
    #     return response.json()
    # else:
    #     logger.error(f"Failed to exchange OAuth code: {response.text}")
    #     return None
    
    # Mock implementation for Phase 1
    return {
        "access_token": f"mock_google_oauth_token_{code[:10]}",
        "refresh_token": f"mock_refresh_token_{code[:10]}",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile"
    }


def create_mcp_error_response(error: Exception, error_code: int = -1) -> Dict[str, Any]:
    """
    Create a standardized MCP error response.
    
    Args:
        error: The exception that occurred
        error_code: MCP error code
        
    Returns:
        MCP-formatted error response
    """
    return {
        "error": {
            "code": error_code,
            "message": str(error),
            "data": {
                "type": type(error).__name__
            }
        }
    }