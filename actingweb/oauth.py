from builtins import str

try:
    from urllib.parse import urlencode as urllib_urlencode
except ImportError:
    from urllib.parse import urlencode as urllib_urlencode
import base64
import json
import logging
import urlfetch
from typing import Optional, Dict, Any
from . import config as config_class

# This function code is from latest urlfetch. For some reason the
# Appengine version of urlfetch does not include links()


def pagination_links(self):
    """Links parsed from HTTP Link header"""
    rets = []
    if "link" in self.headers:
        linkheader = self.headers["link"]
    else:
        return rets
    for i in linkheader.split(","):
        try:
            url, params = i.split(";", 1)
        except ValueError:
            url, params = i, ""
        link = {"url": url.strip('''<> '"''')}
        for param in params.split(";"):
            try:
                k, v = param.split("=")
            except ValueError:
                break
            link[k.strip(''' '"''')] = v.strip(''' '"''')
        rets.append(link)
    return rets


class OAuth:

    def __init__(self, token: Optional[str] = None, config: Optional[config_class.Config] = None):
        self.config = config
        self.token = token
        self.first = None
        self.next = None
        self.prev = None
        self.last_response_code = 0
        self.last_response_message = ""

    def enabled(self):
        if not self.config or not self.config.oauth:
            return False
        if len(self.config.oauth["client_id"]) == 0:
            return False
        else:
            return True

    def set_token(self, token):
        if token:
            self.token = token

    def post_request(self, url, params=None, urlencode=False, basic_auth=False):
        if params:
            if urlencode:
                data = urllib_urlencode(params)
                logging.debug(
                    "Oauth POST request with urlencoded payload: " + url + " " + data
                )
            else:
                data = json.dumps(params)
                logging.debug(
                    "Oauth POST request with JSON payload: " + url + " " + data
                )
        else:
            data = None
            logging.debug("Oauth POST request: " + url)
        if urlencode:
            if self.token:
                if basic_auth:
                    headers = {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": "Basic "
                        + base64.b64encode(self.token.encode("utf-8")).decode("utf-8"),
                    }
                else:
                    headers = {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": "Bearer " + self.token,
                    }
            else:
                headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                }
        else:
            if self.token:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.token,
                }
            else:
                headers = {"Content-Type": "application/json"}
        try:
            response = urlfetch.post(
                url=url, data=data, headers=headers
            )
            if response:
                self.last_response_code = response.status_code
                self.last_response_message = response.content
        except Exception:
            self.last_response_code = 0
            self.last_response_message = "No response"
            logging.warning("Oauth POST failed with exception")
            return None
        if response.status_code == 204:
            return {}
        if response.status_code != 200 and response.status_code != 201:
            logging.info(
                "Error when sending POST request: "
                + str(response.status_code)
                + str(response.content)
            )
            return None
        logging.debug("Oauth POST response JSON:" + str(response.content))
        return json.loads(response.content.decode("utf-8", "ignore"))

    def put_request(self, url, params=None, urlencode=False):
        if params:
            if urlencode:
                data = urllib_urlencode(params)
                logging.debug(
                    "Oauth PUT request with urlencoded payload: " + url + " " + data
                )
            else:
                data = json.dumps(params)
                logging.debug(
                    "Oauth PUT request with JSON payload: " + url + " " + data
                )
        else:
            data = None
            logging.debug("Oauth PUT request: " + url)
        if urlencode:
            if self.token:
                headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": "Bearer " + self.token,
                }
            else:
                headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                }
        else:
            if self.token:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.token,
                }
            else:
                headers = {"Content-Type": "application/json"}
        try:
            response = urlfetch.put(
                url=url, data=data, headers=headers
            )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            self.last_response_code = 0
            self.last_response_message = "No response"
            logging.warning("Oauth PUT failed with exception")
            return None
        if response.status_code == 204:
            return {}
        if response.status_code != 200 and response.status_code != 201:
            logging.info(
                "Error when sending PUT request: "
                + str(response.status_code)
                + str(response.content)
            )
            return None
        logging.debug("Oauth PUT response JSON:" + str(response.content))
        return json.loads(response.content.decode("utf-8", "ignore"))

    def get_request(self, url, params=None):
        if not self.token:
            logging.debug("No token set in get_request()")
            return None
        if params:
            url = url + "?" + urllib_urlencode(params)
        logging.debug("Oauth GET request: " + url)
        try:
            response = urlfetch.get(
                url,
                headers={
                    "Authorization": "Bearer " + self.token,
                },
            )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            self.last_response_code = 0
            self.last_response_message = "No response"
            logging.warning("Oauth GET failed with exception")
            return None
        if response.status_code < 200 or response.status_code > 299:
            logging.info(
                "Error when sending GET request to Oauth: "
                + str(response.status_code)
                + str(response.content)
            )
            return None
        links = pagination_links(response)
        self.next = None
        self.first = None
        self.prev = None
        for link in links:
            logging.debug("Links:" + link["rel"] + ":" + link["url"])
            if link["rel"] == "next":
                self.next = link["url"]
            elif link["rel"] == "first":
                self.first = link["url"]
            elif link["rel"] == "prev":
                self.prev = link["url"]
        return json.loads(response.content.decode("utf-8", "ignore"))

    def head_request(self, url, params=None):
        if not self.token:
            logging.debug("No token set in head_request(()")
            return None
        if params:
            url = url + "?" + urllib_urlencode(params)
        logging.debug("Oauth HEAD request: " + url)
        try:
            response = urlfetch.head(
                url=url, headers={"Authorization": "Bearer " + self.token}
            )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            self.last_response_code = 0
            self.last_response_message = "No response"
            logging.warning("Oauth HEAD failed with exception")
            return None
        if response.status_code < 200 or response.status_code > 299:
            logging.warning(
                "Error when sending HEAD request to Oauth: "
                + str(response.status_code)
                + str(response.content)
            )
            return None
        return response.headers

    def delete_request(self, url):
        if not self.token:
            return None
        logging.debug("Oauth DELETE request: " + url)
        try:
            response = urlfetch.delete(
                url=url, headers={"Authorization": "Bearer " + self.token}
            )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except Exception:
            logging.warning("Spark DELETE failed.")
            self.last_response_code = 0
            self.last_response_message = "No response"
            return None
        if response.status_code < 200 or response.status_code > 299:
            logging.info(
                "Error when sending DELETE request to Oauth: "
                + str(response.status_code)
                + str(response.content)
            )
            return None
        if response.status_code == 204:
            return {}
        try:
            ret = json.loads(response.content.decode("utf-8", "ignore"))
        except (
            urlfetch.UrlfetchException,
            urlfetch.URLError,
            urlfetch.Timeout,
            urlfetch.TooManyRedirects,
        ):
            return {}
        return ret

    def oauth_redirect_uri(self, state: str = "", creator: Optional[str] = None) -> str:
        # Use the new OAuth2 module for redirect URI generation
        try:
            from .oauth2 import create_oauth2_authenticator
            if self.config is not None:
                authenticator = create_oauth2_authenticator(self.config)
                if authenticator.is_enabled():
                    # Use creator as email hint for OAuth2 authentication
                    return authenticator.create_authorization_url(state=state, email_hint=creator or "")
        except Exception as e:
            logging.error(f"Error creating OAuth2 redirect URI: {e}")
        
        # Fallback to legacy implementation
        if not self.config or not self.config.oauth:
            return ""
        params = {
            "response_type": self.config.oauth["response_type"],
            "client_id": self.config.oauth["client_id"],
            "redirect_uri": self.config.oauth["redirect_uri"],
            "scope": self.config.oauth["scope"],
            "state": state,
        }
        
        # Add login_hint for Google OAuth2 if creator (email) is provided
        if creator and "google" in self.config.oauth.get("auth_uri", ""):
            params["login_hint"] = creator
            
        if "oauth_extras" in self.config.oauth:
            oauth_extras = self.config.oauth["oauth_extras"]
            if isinstance(oauth_extras, dict):
                for k, v in oauth_extras.items():
                    if isinstance(v, str) and "dynamic:" in v:
                        if v[8:] == "creator" and creator:
                            v = creator
                    params[k] = v
        uri = self.config.oauth["auth_uri"] + "?" + urllib_urlencode(params)
        logging.debug("OAuth redirect with url: " + uri + " and state:" + state)
        return uri

    def oauth_request_token(self, code=None):
        # Use the new OAuth2 module for token exchange
        try:
            from .oauth2 import create_oauth2_authenticator
            if self.config is not None:
                authenticator = create_oauth2_authenticator(self.config)
                if authenticator.is_enabled() and code:
                    result = authenticator.exchange_code_for_token(code)
                    if result and "access_token" in result:
                        self.token = result["access_token"]
                    return result
        except Exception as e:
            logging.error(f"Error exchanging OAuth2 code for token: {e}")
        
        # Fallback to legacy implementation
        if not code:
            return None
        if not self.config or not self.config.oauth:
            return None
        params = {
            "grant_type": self.config.oauth["grant_type"],
            "client_id": self.config.oauth["client_id"],
            "client_secret": self.config.oauth["client_secret"],
            "code": code,
            "redirect_uri": self.config.oauth["redirect_uri"],
        }
        # Some OAuth2 implementations require Basic auth with client_id and secret
        self.token = (
            self.config.oauth["client_id"] + ":" + self.config.oauth["client_secret"]
        )
        result = self.post_request(
            url=self.config.oauth["token_uri"],
            params=params,
            urlencode=True,
            basic_auth=True,
        )
        if result and "access_token" in result:
            self.token = result["access_token"]
        return result

    def oauth_refresh_token(self, refresh_token):
        # Use the new OAuth2 module for token refresh
        try:
            from .oauth2 import create_oauth2_authenticator
            if self.config is not None:
                authenticator = create_oauth2_authenticator(self.config)
                if authenticator.is_enabled() and refresh_token:
                    result = authenticator.refresh_access_token(refresh_token)
                    if result and "access_token" in result:
                        self.token = result["access_token"]
                    return result
        except Exception as e:
            logging.error(f"Error refreshing OAuth2 token: {e}")
        
        # Fallback to legacy implementation
        if not refresh_token:
            return None
        if not self.config or not self.config.oauth:
            return None
        params = {
            "grant_type": self.config.oauth["refresh_type"],
            "client_id": self.config.oauth["client_id"],
            "client_secret": self.config.oauth["client_secret"],
            "refresh_token": refresh_token,
        }
        # Some OAuth2 implementations require Basic auth with client_id and secret
        self.token = (
            self.config.oauth["client_id"] + ":" + self.config.oauth["client_secret"]
        )
        result = self.post_request(
            url=self.config.oauth["token_uri"],
            params=params,
            urlencode=True,
            basic_auth=True,
        )
        if not result:
            self.token = None
            return None
        self.token = result["access_token"]
        return result
