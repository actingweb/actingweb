from __future__ import absolute_import
from builtins import str
from builtins import object
import logging
import time

from . import oauth
import base64
import math
from . import actor
from . import trust
from . import config as config_class

# This is where each path and subpath in actingweb is assigned an authentication type
# Fairly simple: /oauth is always oauth, /www can be either basic+trust or
# oauth through config.py, and everything else is basic+trust


def select_auth_type(path, subpath, config=None):
    """Selects authentication type based on path and subpath.

    Currently are only basic and oauth supported. Peer auth is automatic if an Authorization Bearer <token> header is
    included in the http request.
    """
    if path == 'oauth':
        return 'oauth'
    if path == 'www':
        return config.www_auth
    if subpath == 'oauth':
        return 'oauth'
    return 'basic'


def add_auth_response(appreq=None, auth_obj=None):
    """Called after init_actingweb() if add_response was set to False, and now responses should be added."""
    if not appreq or not auth_obj:
        return False
    logging.debug("add_auth_response: " + str(auth_obj.response['code']) + ":" + auth_obj.response['text'])
    appreq.set_status(auth_obj.response['code'], auth_obj.response['text'])
    if auth_obj.response['code'] == 302:
        appreq.set_redirect(url=auth_obj.redirect)
    elif auth_obj.response['code'] == 401:
        appreq.write("Authentication required")
    for h, v in list(auth_obj.response['headers'].items()):
        appreq.headers[h] = v
    return True


def init_actingweb(appreq=None, actor_id=None, path='', subpath='', add_response=True, config=None):
    """Initialises actingweb by loading a config object, an actor object, and authentication object.
    

            More details about the authentication can be found in the auth object. If add_response is True,
            appreq.response
            will be changed according to authentication result. If False, appreq will not be touched.
            authn_done (bool), response['code'], response['text'], and response['headers'] will indicate results of
            the authentication process
            and need to be acted upon.
            200 is access approved
            302 is redirect and auth_obj.redirect contains redirect location where response must be redirected
            401 is authentication required, response['headers'] must be added to response
            403 is forbidden, text in response['text']
    """

    fullpath = '/' + path + '/' + subpath
    auth_type = select_auth_type(path=path, subpath=subpath, config=config)
    auth_obj = Auth(actor_id, auth_type=auth_type, config=config)
    if not auth_obj.actor:
        if add_response:
            appreq.response.set_status(404, 'Actor not found')
        return None, None
    auth_obj.check_authentication(appreq=appreq, path=fullpath)
    if add_response:
        add_auth_response(appreq.response, auth_obj)
    # Initialize the on_aw object with auth (.actor) and webobj (.config) for functions in on_aw
    appreq.on_aw.aw_init(auth=auth_obj, webobj=appreq)
    return auth_obj.actor, auth_obj


class Auth(object):
    """ The auth class handles authentication and authorisation for the various schemes supported.

    The helper function init_actingweb() can be used to give you an auth object and do authentication (or can be called
    directly).
    The check_authentication() function checks the various authentication schemes against the path and does proper
    authentication.
    There are three types supported: basic (using creator credentials), token (received when trust is created), or
    oauth (used to bind
    an actor to an oauth-enabled external service, as well as to log into /www path where interactive web functionality
    of the actor
    is available).
    The check_authorisation() function validates the authenticated user against the config.py access list.
    check_token_auth() can be called from outside the class to do a simple peer/bearer token verification.
    The OAuth helper functions are used to:
    process_oauth_callback() - process an OAuth callback as part of an OAuth flow and exchange code with a valid token
    validate_oauth_token() - validate and, if necessary, refresh a token
    set_cookie_on_cookie_redirect() - set a session cookie in the browser to the token value (called AFTER OAuth has
    been
    done!)

    The response[], acl[], and authn_done variables are useful outside Auth(). authn_done is set when authentication has
    been done and
    a final authentication status can be found in response[].

         self.response = {
            "code": 403,                # Result code (http)
            "text": "Forbidden",        # Proposed response text
            "headers": [],              # Headers to add to response after authentication has been done
        }    
        self.acl = {
            "authenticated": False, # Has authentication been verified and passed?
            "authorised": False,    # Has authorisation been done and appropriate acls set?
            "rights": '',           # "a", "r" (approve or reject)
            "relationship": None,   # E.g. creator, friend, admin, etc
            "peerid": '',           # Peerid if there is a relationship
            "approved": False,      # True if the peer is approved
        }

    """

    def __init__(self, actor_id, auth_type='basic', config=None):
        if not config:
            self.config = config_class.Config()
        else:
            self.config = config
        self.token = None
        self.cookie_redirect = None
        self.cookie = None
        self.type = auth_type
        self.trust = None
        self.oauth = None
        # Proposed response code after check_authentication() or authorise() have been called
        self.response = {'code': 403, 'text': "Forbidden", 'headers': {}}
        # Whether authentication is complete or not (depends on flow)
        self.authn_done = False
        # acl stores the actual verified credentials and access rights after
        # authentication and authorisation have been done
        self.acl = {
            "authenticated": False,  # Has authentication been verified and passed?
            "authorised": False,    # Has authorisation been done and appropriate acls set?
            "rights": '',           # "a", "r" (approve or reject)
            "relationship": None,   # E.g. creator, friend, admin, etc
            "peerid": '',           # Peerid if there is a relationship
            "approved": False,      # True if the peer is approved
        }
        self.actor = actor.Actor(actor_id, config=self.config)
        if not self.actor.id:
            self.actor = None
            self.oauth = oauth.OAuth(token=None, config=self.config)
            self.token = None
            self.expiry = None
            self.refresh_expiry = None
            self.refresh_token = None
            return
        # We need to initialise oauth for use towards the external oauth service
        self.property = 'oauth_token'  # Property name used to set self.token
        self.token = self.actor.get_property(self.property).value
        self.oauth = oauth.OAuth(token=self.token, config=self.config)
        self.expiry = self.actor.get_property('oauth_token_expiry').value
        self.refresh_expiry = self.actor.get_property('oauth_refresh_token_expiry').value
        self.refresh_token = self.actor.get_property('oauth_refresh_token').value    
        if self.type == 'basic':
            self.realm = self.config.auth_realm
        elif self.type == 'oauth':
            if self.oauth.enabled():
                self.cookie = 'oauth_token'
                if self.actor.get_property('cookie_redirect').value:
                    self.cookie_redirect = self.config.root + \
                        self.actor.get_property('cookie_redirect').value
                else:
                    self.cookie_redirect = None
                self.redirect = str(self.config.root + self.actor.id + '/oauth')
            else:
                self.type = 'none'

    def __process_oauth_accept(self, result):
        if not result:
            return None
        if not result['access_token']:
            logging.info('No token in response')
            return None
        now = time.time()
        self.token = result['access_token']
        self.actor.set_property('oauth_token', self.token)
        self.expiry = str(now + result['expires_in'])
        self.actor.set_property('oauth_token_expiry', self.expiry)
        if 'refresh_token' in result:
            self.refresh_token = result['refresh_token']
            if 'refresh_token_expires_in' in result:
                self.refresh_expiry = str(now + result['refresh_token_expires_in'])
            else:
                self.refresh_expiry = str(now + (365*24*3600))  # Set a default expiry 12 months ahead
            self.actor.set_property('oauth_refresh_token', self.refresh_token)
            self.actor.set_property('oauth_refresh_token_expiry', self.refresh_expiry)

    def process_oauth_callback(self, code):
        """ Called when a callback is received as part of an OAuth flow to exchange code for a bearer token."""
        if not code:
            return False
        if not self.oauth:
            logging.warning('Call to processOauthCallback() with oauth disabled.')
            return False
        result = self.oauth.oauth_request_token(code)
        if not result or (result and 'access_token' not in result):
            logging.warning('No token in response')
            return False
        self.__process_oauth_accept(result)
        return True

    def validate_oauth_token(self, lazy=False):
        """ Called to validate the token as part of a web-based flow.

            Returns the redirect URI to send back to the browser or empty string.
            If lazy is true, refresh_token is used only if < 24h until expiry.
        """
        if not self.token or not self.expiry:
            return self.oauth.oauth_redirect_uri(state=self.actor.id)
        now = time.time()
        # Is the token still valid?
        if now < (float(self.expiry) - 20.0):
            return ""
        # Has refresh_token expired?
        if now > (float(self.refresh_expiry) - 20.0):
            return self.oauth.oauth_redirect_uri(state=self.actor.id)
        # Do we have more than a day until refresh token expiry?
        if lazy and now < (float(self.refresh_expiry) - (3600.0 * 24)):
            return ""
        # Refresh the token
        result = self.oauth.oauth_refresh_token(self.refresh_token)
        if not result:
            return self.oauth.oauth_redirect_uri(state=self.actor.id)
        self.__process_oauth_accept(result)
        return ""

    def oauth_get(self, url=None, params=None):
        """Used to call GET from the attached oauth service.

           Uses oauth.get_request(), but refreshes token if necessary.
           The function fails if token is invalid and no refresh is
           possible. For web-based flows, validate_oauth_token() needs
           to be used to validate token and get redirect URI for new
           authorization flow.
        """
        if not url:
            return None
        ret = self.oauth.get_request(url=url, params=params)
        code1 = self.oauth.last_response_code
        if (ret and any(ret)) or code1 == 204 or code1 == 201 or code1 == 404:
            return ret
        if self.actor and self.actor.id and (not ret or code1 == 401 or code1 == 403):
            refresh = self.oauth.oauth_refresh_token(refresh_token=self.refresh_token)
            if not refresh:
                logging.warning('Tried to refresh token and failed for Actor(' + self.actor.id + ')')
            else:
                self.__process_oauth_accept(refresh)
                ret2 = self.oauth.get_request(url=url, params=params)
                code2 = self.oauth.last_response_code
                if ret2 and any(ret2) or code2 == 204 or code2 == 201:
                    return ret2
        return None

    def oauth_head(self, url=None, params=None):
        """Used to call HEAD from the attached oauth service.

           Uses oauth.head_request((), but refreshes token if necessary.
           The function fails if token is invalid and no refresh is
           possible. For web-based flows, validate_oauth_token() needs
           to be used to validate token and get redirect URI for new
           authorization flow.
        """
        if not url:
            return None
        ret = self.oauth.head_request(url=url, params=params)
        code1 = self.oauth.last_response_code
        if (ret and any(ret)) or code1 == 204 or code1 == 201 or code1 == 404:
            return ret
        if self.actor and self.actor.id and (not ret or code1 == 401 or code1 == 403):
            refresh = self.oauth.oauth_refresh_token(refresh_token=self.refresh_token)
            if not refresh:
                logging.warning('Tried to refresh token and failed for Actor(' + self.actor.id + ')')
            else:
                self.__process_oauth_accept(refresh)
                ret2 = self.oauth.head_request(url=url, params=params)
                code2 = self.oauth.last_response_code
                if ret2 and any(ret2) or code2 == 204 or code2 == 201:
                    return ret2
        return None

    def oauth_delete(self, url=None):
        """Used to call DELETE from the attached oauth service.

           Uses oauth.delete_request((), but refreshes token if necessary.
           The function fails if token is invalid and no refresh is
           possible. For web-based flows, validate_oauth_token() needs
           to be used to validate token and get redirect URI for new
           authorization flow.
        """
        if not url:
            return None
        ret = self.oauth.delete_request(url=url)
        code1 = self.oauth.last_response_code
        if (ret and any(ret)) or code1 == 204 or code1 == 404:
            return ret
        if self.actor and self.actor.id and (code1 == 401 or code1 == 403):
            refresh = self.oauth.oauth_refresh_token(refresh_token=self.refresh_token)
            if not refresh:
                logging.warning('Tried to refresh token and failed for Actor(' + self.actor.id + ')')
            else:
                self.__process_oauth_accept(refresh)
                ret2 = self.oauth.delete_request(url=url)
                code2 = self.oauth.last_response_code
                if ret2 and any(ret2) or code2 == 204:
                    return ret2
        return None

    def oauth_post(self, url=None, params=None, urlencode=False):
        """Used to call POST from the attached oauth service.

           Uses oauth.post_request(), but refreshes token if necessary.
           The function fails if token is invalid and no refresh is
           possible. For web-based flows, validate_oauth_token() needs
           to be used to validate token and get redirect URI for new
           authorization flow.
        """
        if not url:
            return None
        ret = self.oauth.post_request(url=url, params=params, urlencode=urlencode)
        code1 = self.oauth.last_response_code
        if (ret and any(ret)) or code1 == 204 or code1 == 201 or code1 == 404:
            return ret
        if self.actor and self.actor.id and (code1 == 401 or code1 == 403):
            refresh = self.oauth.oauth_refresh_token(refresh_token=self.refresh_token)
            if not refresh:
                logging.warning('Tried to refresh token and failed for Actor(' + self.actor.id + ')')
            else:
                self.__process_oauth_accept(refresh)
                ret2 = self.oauth.post_request(url=url, params=params, urlencode=urlencode)
                code2 = self.oauth.last_response_code
                if ret2 and any(ret2) or code2 == 204 or code2 == 201:
                    return ret2
        return None

    def oauth_put(self, url=None, params=None, urlencode=False):
        """Used to call PUT from the attached oauth service.

           Uses oauth.put_request(), but refreshes token if necessary.
           The function fails if token is invalid and no refresh is
           possible. For web-based flows, validate_oauth_token() needs
           to be used to validate token and get redirect URI for new
           authorization flow.
        """
        if not url:
            return None
        ret = self.oauth.put_request(url=url, params=params, urlencode=urlencode)
        code1 = self.oauth.last_response_code
        if (ret and any(ret)) or code1 == 204 or code1 == 201 or code1 == 404:
            return ret
        if self.actor and self.actor.id and (code1 == 401 or code1 == 403):
            refresh = self.oauth.oauth_refresh_token(refresh_token=self.refresh_token)
            if not refresh:
                logging.warning('Tried to refresh token and failed for Actor(' + self.actor.id + ')')
            else:
                self.__process_oauth_accept(refresh)
                ret2 = self.oauth.put_request(url=url, params=params, urlencode=urlencode)
                code2 = self.oauth.last_response_code
                if ret2 and any(ret2) or code2 == 204 or code2 == 201:
                    return ret2
        return None

    # Called from a www page (browser access) to verify that a cookie has been
    # set to the actor's valid token.
    def __check_cookie_auth(self, appreq, path):
        if not path:
            path = ''
        if not self.actor:
            return False
        if self.token:
            now = time.time()
            if appreq.request.cookies and self.cookie in appreq.request.cookies:
                authz = appreq.request.cookies[self.cookie]
            else:
                authz = ''
            if appreq.request.get('refresh') and appreq.request.get('refresh').lower() == 'true':
                # Clear cookie and do a refresh if refresh=True is in GET param
                authz = ''
            if authz == self.token and now < (float(self.expiry) - 20.0):
                logging.debug('Authorization cookie header matches a valid token')
                self.acl["relationship"] = "creator"
                self.acl["authenticated"] = True
                self.response['code'] = 200
                self.authn_done = True
                return True
            elif authz != self.token:
                self.actor.delete_property(self.property)
                logging.debug('Authorization cookie header does not match a valid token')
                self.response['code'] = 403
                self.response['text'] = "Forbidden"
                self.authn_done = True
        if self.cookie_redirect:
            logging.debug('Cookie redirect already set!')
        else:
            self.actor.set_property('cookie_redirect', self.actor.id + path)
            self.cookie_redirect = '/' + self.actor.id + path
        self.response['code'] = 302
        return False

    def set_cookie_on_cookie_redirect(self, appreq):
        """ Called after successful auth to set the cookie with the token value."""
        if not self.cookie_redirect:
            return False
        if not self.token:
            logging.warning("Trying to set cookie when no token value can be found.")
            return False
        logging.debug('Setting Authorization cookie: ' + str(self.token))
        appreq.response.set_cookie(self.cookie, str(self.token),
                                   max_age=1209600, path='/', secure=True)
        appreq.response.set_redirect(str(self.cookie_redirect))
        self.actor.delete_property('cookie_redirect')
        return True

    def __check_basic_auth_creator(self, appreq):
        if self.type != 'basic':
            logging.warning("Trying to do basic auth when auth type is not basic")
            self.response['code'] = 403
            self.response['text'] = "Forbidden"
            return False
        if not self.actor.passphrase:
            logging.warning("Trying to do basic auth when no passphrase value can be found.")
            self.response['code'] = 403
            self.response['text'] = "Forbidden"
            return False
        if 'Authorization' not in appreq.request.headers:
            self.response['headers']['WWW-Authenticate'] = 'Basic realm="' + self.realm + '"'
            self.response['code'] = 401
            self.response['text'] = "Authentication required"
            return False
        authz = appreq.request.headers['Authorization']
        (basic, token) = authz.split(' ')
        if basic.lower() != "basic":
            self.response['code'] = 403
            self.response['text'] = "No basic auth in Authorization header"
            logging.debug("No basic auth in Authorization header")
            return False
        self.authn_done = True
        au = authz.split(' ')[1]
        au = au.encode('utf-8')
        au = base64.b64decode(au)
        (username, password) = au.split(b':')
        password = password.decode('utf-8')
        username = username.decode('utf-8')
        if username != self.actor.creator:
            self.response['code'] = 403
            self.response['text'] = "Invalid username or password"
            logging.debug("Wrong creator username")
            return False
        if password != self.actor.passphrase:
            self.response['code'] = 403
            self.response['text'] = "Invalid username or password"
            logging.debug("Wrong creator passphrase(" +
                          password + ") correct(" + self.actor.passphrase + ")")
            return False
        self.acl["relationship"] = "creator"
        self.acl["authenticated"] = True
        self.response['code'] = 200
        self.response['text'] = "Ok"
        return True

    def check_token_auth(self, appreq):
        """ Called with an http request to check the Authorization header and validate if we have a peer with
        this token."""
        if 'Authorization' not in appreq.request.headers:
            return False
        auth = appreq.request.headers['Authorization']
        (bearer, token) = auth.split(' ')
        if bearer.lower() != "bearer":
            return False
        self.authn_done = True
        trustee = self.actor.get_property('trustee_root').value
        # If trustee_root is set, creator name is 'trustee' and
        # bit strength of passphrase is > 80, use passphrase as
        # token
        if trustee and self.actor.creator.lower() == 'trustee':
            if math.floor(len(self.actor.passphrase)*math.log(94, 2)) > 80:
                if token == self.actor.passphrase:
                    self.acl["relationship"] = 'trustee'
                    self.acl["peerid"] = ''
                    self.acl["approved"] = True
                    self.acl["authenticated"] = True
                    self.response['code'] = 200
                    self.response['text'] = "Ok"
                    self.token = self.actor.passphrase
                    return True
            else:
                logging.warning('Attempted trustee bearer token auth with <80 bit strength token.')
        tru = trust.Trust(actor_id=self.actor.id, token=token, config=self.config)
        new_trust = tru.get()
        if new_trust:
            logging.debug('Found trust with token: (' + str(new_trust) + ')')
            if new_trust["peerid"] == self.actor.id:
                logging.error("Peer == actor!!")
                return False
        if new_trust and len(new_trust) > 0:
            self.acl["relationship"] = new_trust["relationship"]
            self.acl["peerid"] = new_trust["peerid"]
            self.acl["approved"] = new_trust["approved"]
            self.acl["authenticated"] = True
            self.response['code'] = 200
            self.response['text'] = "Ok"
            self.token = new_trust["secret"]
            self.trust = new_trust
            return True
        else:
            return False

    def check_authentication(self, appreq, path):
        """ Checks authentication in appreq, redirecting back to path if oauth is done."""
        logging.debug('Checking authentication, token auth...')
        if self.check_token_auth(appreq):
            return
        elif self.type == 'oauth':
            logging.debug('Checking authentication, oauth cookie...')
            self.__check_cookie_auth(appreq=appreq, path=path)
            return
        elif self.type == 'basic':
            logging.debug('Checking authentication, basic auth...')
            self.__check_basic_auth_creator(appreq=appreq)
            return
        logging.debug('Authentication done, and failed')
        self.authn_done = True
        self.response['code'] = 403
        self.response['text'] = "Forbidden"
        return

    def check_authorisation(self, path='', subpath='', method='', peerid='',
                            approved=True):
        """ Checks if the authenticated user has acl access rights in config.py.

        Takes the path, subpath, method, and peerid of the path (if auth user
        is different from the peer that owns the path, e.g. creator). If approved
        is False, then the trust relationship does not need to be approved for
        access"""
        if len(self.acl["peerid"]) > 0 and approved and self.acl["approved"] is False:
            logging.debug('Rejected authorization because trust relationship is not approved.')
            return False
        if self.acl["relationship"]:
            relationship = self.acl["relationship"].lower()
        else:
            relationship = ''
        method = method.upper()
        self.acl["authorised"] = True
        self.acl["rights"] = "r"
        if len(path) == 0:
            return False
        if not subpath:
            subpath = ''
        fullpath = path.lower() + '/' + subpath.lower()
        # ACLs: ('role', 'path', 'METHODS', 'access')
        logging.debug('Testing access for (' + relationship +
                      ' ' + self.acl["peerid"] + ') on (' + fullpath + ' ' +
                      peerid + ') using method ' + method)
        for acl in self.config.access:
            if acl[0] == 'any' and not self.acl["authenticated"]:
                continue
            if len(acl[0]) > 0 and acl[0] != 'any' and acl[0] != relationship and acl[0] != 'owner':
                continue  # no match on relationship
            if acl[0] == relationship or acl[0] == 'any' or \
                    len(acl[0]) == 0 or (acl[0] == 'owner' and len(peerid) > 0 and
                                         self.acl["peerid"] == peerid):
                if fullpath.find(acl[1]) == 0:
                    if len(acl[2]) == 0 or acl[2].find(method) != -1:
                        self.acl["rights"] = acl[3]
                        logging.debug('Granted ' + acl[3] +
                                      ' access with ACL:' +
                                      str(acl))
                        return True
        return False
