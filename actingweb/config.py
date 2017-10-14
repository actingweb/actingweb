__all__ = [
    'config',
]

import uuid
import binascii
import logging
import importlib


class config():

    def __init__(self, database='gae'):
        self.database = database
        self.db_property = importlib.import_module(".db_property", "actingweb" + ".db_" + database)
        #########
        # Basic settings for this app
        #########
        self.ui = True                                      # Turn on the /www path
        self.devtest = True                                 # Enable /devtest path for test purposes, MUST be False in production
        self.unique_creator = False                          # Will enforce unique creator field across all actors
        self.force_email_prop_as_creator = True             # Use "email" property to set creator value (after creation and property set)
        self.www_auth = "basic"                             # basic or oauth: basic for creator + bearer tokens
        self.fqdn = "actingwebdemo-dev.appspot.com"         # The host and domain, i.e. FQDN, of the URL
        self.proto = "https://"                             # http or https
        self.logLevel = logging.DEBUG  # Change to WARN for production, DEBUG for debugging, and INFO for normal testing
        #########
        # ActingWeb settings for this app
        #########
        self.type = "urn:actingweb:actingweb.org:gae-demo"  # The app type this actor implements
        self.desc = "GAE Demo actor: "                      # A human-readable description for this specific actor
        self.version = "1.0"                                # A version number for this app
        self.info = "http://actingweb.org/"                 # Where can more info be found
        self.aw_version = "0.9"                             # This app follows the actingweb specification specified
        self.aw_supported = "www,oauth,callbacks"           # This app supports the following options
        self.specification = ""                             # URL to a RAML/Swagger etc definition if available
        self.aw_formats = "json"                            # These are the supported formats
        #########
        # Known and trusted ActingWeb actors
        #########
        self.actors = {
            '<SHORTTYPE>': {
                'type': 'urn:<ACTINGWEB_TYPE>',
                'factory': '<ROOT_URI>',
                'relationship': 'friend',                   # associate, friend, partner, admin
                },
            'myself': {
                'type': self.type,
                'factory': self.proto + self.fqdn + '/',
                'relationship': 'friend',                   # associate, friend, partner, admin
                },
        }
        #########
        # OAuth settings for this app, fill in if OAuth is used
        #########
        self.oauth = {
            'client_id': "",                                # An empty client_id turns off oauth capabilities
            'client_secret': "",
            'redirect_uri': self.proto + self.fqdn + "/oauth",
            'scope': "",
            'auth_uri': "",
            'token_uri': "",
            'response_type': "code",
            'grant_type': "authorization_code",
            'refresh_type': "refresh_token",
        }
        self.bot = {
            'token': '',
            'email': '',
        }
        #########
        # Trust settings for this app
        #########
        self.default_relationship = "associate"                # Default relationship if not specified
        self.auto_accept_default_relationship = False          # True if auto-approval
        # List of paths and their access levels
        # Matching is done top to bottom stopping at first match (role, path)
        # If no match is found on path with the correct role, access is rejected
        # <type> and <id> are used as templates for trust types and ids
        self.access = [
            # (role, path, method, access), e.g. ('friend', '/properties', '', 'rw')
            # Roles: creator, trustee, associate, friend, partner, admin, any (i.e. authenticated),
            #        owner (i.e. trust peer owning the entity)
            #        + any other new role for this app
            # Methods: GET, POST, PUT, DELETE
            # Access: a (allow) or r (reject)
            ('', 'meta', 'GET', 'a'),                       # Allow GET to anybody without auth
            ('', 'oauth', '', 'a'),                         # Allow any method to anybody without auth
            ('owner', 'callbacks/subscriptions', 'POST', 'a'),   # Allow owners on subscriptions
            ('', 'callbacks', '', 'a'),                     # Allow anybody callbacks witout auth
            ('creator', 'www', '', 'a'),                    # Allow only creator access to /www
            ('creator', 'properties', '', 'a'),             # Allow creator access to /properties
            ('associate', 'properties', 'GET', 'a'),        # Allow GET only to associate
            ('friend', 'properties', '', 'a'),              # Allow friend/partner/admin all
            ('partner', 'properties', '', 'a'),
            ('admin', 'properties', '', 'a'),
            ('creator', 'resources', '', 'a'),
            ('friend', 'resources', '', 'a'),               # Allow friend/partner/admin all
            ('partner', 'resources', '', 'a'),
            ('admin', 'resources', '', 'a'),
            ('', 'trust/<type>', 'POST', 'a'),              # Allow unauthenticated POST
            ('owner', 'trust/<type>/<id>', '', 'a'),        # Allow trust peer full access
            ('creator', 'trust', '', 'a'),                  # Allow access to all to
            ('trustee', 'trust', '', 'a'),                  # creator/trustee/admin
            ('admin', 'trust', '', 'a'),
            ('owner', 'subscriptions', '', 'a'),             # Owner can create++ own subscriptions
            ('creator', 'subscriptions', '', 'a'),           # Creator can do everything
            ('trustee', 'subscriptions', '', 'a'),           # Trustee can do everything
            ('creator', '/', '', 'a'),                       # Root access for actor
            ('trustee', '/', '', 'a'),
            ('admin', '/', '', 'a'),
        ]
        #########
        # Only touch the below if you know what you are doing
        #########
        self.root = self.proto + self.fqdn + "/"            # root URI used to identity actor externally
        self.auth_realm = self.fqdn                         # Authentication realm used in Basic auth

    def newUUID(self, seed):
        return uuid.uuid5(uuid.NAMESPACE_URL, seed).get_hex()

    def newToken(self, length=40):
        return binascii.hexlify(os.urandom(int(length // 2)))

