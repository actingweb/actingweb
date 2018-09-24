from builtins import object
import uuid
import binascii
import logging
import importlib
import os


class Config(object):

    def __init__(self, **kwargs):
        #########
        # Basic settings for this app
        #########
        # Values that can be changed as part of instantiating config
        self.fqdn = "actingwebdemo-dev.appspot.com"  # The host and domain, i.e. FQDN, of the URL
        self.proto = "https://"  # http or https
        self.env = ''
        self.database = 'dynamodb'
        # Turn on the /www path
        self.ui = True
        # Enable /devtest path for test purposes, MUST be False in production
        self.devtest = True
        # Will enforce unique creator field across all actors
        self.unique_creator = False
        # Use "email" property to set creator value (after creation and property set)
        self.force_email_prop_as_creator = True
        # basic or oauth: basic for creator + bearer tokens
        self.www_auth = "basic"
        self.logLevel = logging.DEBUG
        # Change to WARN for production, DEBUG for debugging, and INFO for normal testing
        #########
        # Configurable ActingWeb settings for this app
        #########
        self.aw_type = "urn:actingweb:actingweb.org:gae-demo"  # The app type this actor implements
        self.desc = "GAE Demo actor: "                      # A human-readable description for this specific actor
        self.specification = ""                             # URL to a RAML/Swagger etc definition if available
        self.version = "1.0"                                # A version number for this app
        self.info = "http://actingweb.org/"                 # Where can more info be found
        #########
        # Trust settings for this app
        #########
        self.default_relationship = "associate"  # Default relationship if not specified
        self.auto_accept_default_relationship = False  # True if auto-approval
        # Pick up the config variables
        for k, v in kwargs.items():
            if k == 'database':
                self.database = v
                if v == 'gae':
                    self.env = 'appengine'
                elif v == 'dynamodb':
                    self.env = 'aws'
            elif k == 'fqdn':
                self.fqdn = v
            elif k == 'proto':
                self.proto = v
            elif k == 'ui':
                self.ui = v
            elif k == 'devtest':
                self.devtest = v
            elif k == 'unique_creator':
                self.unique_creator = v
            elif k == 'force_email_prop_as_creator':
                self.force_email_prop_as_creator = v
            elif k == 'www_auth':
                self.www_auth = v
            elif k == 'logLevel':
                if v == "DEBUG":
                    self.logLevel = logging.DEBUG
                elif v == "WARN":
                    self.logLevel = logging.WARN
                elif v == "INFO":
                    self.logLevel = logging.INFO
            elif k == "aw_type":
                self.aw_type = v
            elif k == "desc":
                self.desc = v
            elif k == "specification":
                self.specification = v
            elif k == "version":
                self.version = v
            elif k == "info":
                self.info = v
            elif k == "default_relationship":
                self.default_relationship = v
            elif k == 'auto_accept_default_relationship':
                self.auto_accept_default_relationship = v
        #########
        # Known and trusted ActingWeb actors
        #########
        self.actors = {
            '<SHORTTYPE>': {
                'type': 'urn:<ACTINGWEB_TYPE>',
                'factory': '<ROOT_URI>',
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
            ('friend', 'subscriptions/<id>', '', 'a'),       # Owner can create subscriptions
            ('creator', 'subscriptions', '', 'a'),           # Creator can do everything
            ('trustee', 'subscriptions', '', 'a'),           # Trustee can do everything
            ('creator', '/', '', 'a'),                       # Root access for actor
            ('trustee', '/', '', 'a'),
            ('admin', '/', '', 'a'),
        ]
        # Pick up the more complex config variables
        for k, v in kwargs.items():
            if k == 'actors':
                self.actors = v
            elif k == 'oauth':
                self.oauth = v
            elif k == 'bot':
                self.bot = v
            elif k == 'access':
                self.access = v
        if 'myself' not in self.actors:
            # Add myself as a known type
            self.actors['myself'] = {
                'type': self.aw_type,
                'factory': self.proto + self.fqdn + '/',
                'relationship': 'friend',  # associate, friend, partner, admin
            }
        # Dynamically load all the database modules
        self.DbActor = importlib.import_module(".db_actor", "actingweb" + ".db_" + self.database)
        self.DbPeerTrustee = importlib.import_module(".db_peertrustee", "actingweb" + ".db_" + self.database)
        self.DbProperty = importlib.import_module(".db_property", "actingweb" + ".db_" + self.database)
        self.DbAttribute = importlib.import_module(".db_attribute", "actingweb" + ".db_" + self.database)
        self.DbSubscription = importlib.import_module(".db_subscription", "actingweb" + ".db_" + self.database)
        self.DbSubscriptionDiff = importlib.import_module(".db_subscription_diff", "actingweb" + ".db_" + self.database)
        self.DbTrust = importlib.import_module(".db_trust", "actingweb" + ".db_" + self.database)
        self.module = {}
        if self.env == 'appengine':
            self.module["deferred"] = importlib.import_module(".deferred", "google.appengine.api")
            self.module["urlfetch"] = importlib.import_module(".urlfetch", "google.appengine.ext")
        else:
            self.module["deferred"] = None
            self.module["urlfetch"] = importlib.import_module("urlfetch")
        #########
        # ActingWeb settings for this app
        #########
        self.aw_version = "1.0"                             # This app follows the actingweb specification specified
        self.aw_supported = "www,oauth,callbacks,trust,onewaytrust,subscriptions," \
                            "actions,resources,methods,sessions,nestedproperties" # This app supports these options
        self.aw_formats = "json"                            # These are the supported formats
        #########
        # Only touch the below if you know what you are doing
        #########
        if self.env == 'appengine':
            logging.getLogger().handlers[0].setLevel(self.logLevel)  # Hack to get access to GAE logger
        else:
            logging.basicConfig(level=self.logLevel)
            # Turn off debugging for pynamodb and botocore, too noisy
            if self.logLevel == logging.DEBUG:
                log = logging.getLogger("pynamodb")
                log.setLevel(logging.INFO)
                log.propagate = True
                log = logging.getLogger("botocore")
                log.setLevel(logging.INFO)
                log.propagate = True
        self.root = self.proto + self.fqdn + "/"            # root URI used to identity actor externally
        self.auth_realm = self.fqdn                         # Authentication realm used in Basic auth

    @staticmethod
    def new_uuid(seed):
        return uuid.uuid5(uuid.NAMESPACE_URL, str(seed)).hex

    @staticmethod
    def new_token(length=40):
        tok = binascii.hexlify(os.urandom(int(length // 2)))
        return tok.decode('utf-8')
