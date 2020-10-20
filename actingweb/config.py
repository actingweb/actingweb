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
        # The host and domain, i.e. FQDN, of the URL
        self.fqdn = "actingwebdemo-dev.appspot.com"
        self.proto = "https://"  # http or https
        self.env = ''
        self.database = 'dynamodb'
        # Turn on the /www path
        self.ui = True
        # Enable /devtest path for test purposes, MUST be False in production
        self.devtest = True
        # Enable migrate if you want to turn on code that enables migration from one version to another
        # 2.4.4 : migrate oauth properties and email to internal attributes (myself.store)
        self.migrate_2_5_0 = True
        # Will enforce unique creator field across all actors
        self.unique_creator = False
        # Use "email" internal value to set creator value (after creation and property set)
        self.force_email_prop_as_creator = True
        # basic or oauth: basic for creator + bearer tokens
        self.www_auth = "basic"
        self.logLevel = logging.DEBUG
        # Change to WARN for production, DEBUG for debugging, and INFO for normal testing
        #########
        # Configurable ActingWeb settings for this app
        #########
        # The app type this actor implements
        self.aw_type = "urn:actingweb:actingweb.org:gae-demo"
        # A human-readable description for this specific actor
        self.desc = "GAE Demo actor: "
        # URL to a RAML/Swagger etc definition if available
        self.specification = ""
        # A version number for this app
        self.version = "1.0"
        # Where can more info be found
        self.info = "http://actingweb.org/"
        #########
        # Trust settings for this app
        #########
        # Default relationship if not specified
        self.default_relationship = "associate"
        self.auto_accept_default_relationship = False  # True if auto-approval
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
            # An empty client_id turns off oauth capabilities
            'client_id': "",
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
            # (role, path, method, access), e.g. ('friend', '/properties', '', 'a')
            # Roles: creator, trustee, associate, friend, partner, admin, any (i.e. authenticated),
            #        owner (i.e. trust peer owning the entity)
            #        + any other new role for this app
            # Methods: GET, POST, PUT, DELETE
            # Access: a (allow) or r (reject)
            # Allow GET to anybody without auth
            ('', 'meta', 'GET', 'a'),
            # Allow any method to anybody without auth
            ('', 'oauth', '', 'a'),
            # Allow owners on subscriptions
            ('owner', 'callbacks/subscriptions', 'POST', 'a'),
            # Allow anybody callbacks witout auth
            ('', 'callbacks', '', 'a'),
            # Allow only creator access to /www
            ('creator', 'www', '', 'a'),
            # Allow creator access to /properties
            ('creator', 'properties', '', 'a'),
            # Allow GET only to associate
            ('associate', 'properties', 'GET', 'a'),
            # Allow friend/partner/admin all
            ('friend', 'properties', '', 'a'),
            ('partner', 'properties', '', 'a'),
            ('admin', 'properties', '', 'a'),
            ('creator', 'resources', '', 'a'),
            # Allow friend/partner/admin all
            ('friend', 'resources', '', 'a'),
            ('partner', 'resources', '', 'a'),
            ('admin', 'resources', '', 'a'),
            # Allow unauthenticated POST
            ('', 'trust/<type>', 'POST', 'a'),
            # Allow trust peer full access
            ('owner', 'trust/<type>/<id>', '', 'a'),
            # Allow access to all to
            ('creator', 'trust', '', 'a'),
            # creator/trustee/admin
            ('trustee', 'trust', '', 'a'),
            ('admin', 'trust', '', 'a'),
            # Owner can create++ own subscriptions
            ('owner', 'subscriptions', '', 'a'),
            # Owner can create subscriptions
            ('friend', 'subscriptions/<id>', '', 'a'),
            # Creator can do everything
            ('creator', 'subscriptions', '', 'a'),
            # Trustee can do everything
            ('trustee', 'subscriptions', '', 'a'),
            # Root access for actor
            ('creator', '/', '', 'a'),
            ('trustee', '/', '', 'a'),
            ('admin', '/', '', 'a'),
        ]
        # Pick up the config variables
        for k, v in kwargs.items():
            self.__setattr__(k, v)
        if self.database == 'gae':
            self.env = 'appengine'
        elif self.database == 'dynamodb':
            self.env = 'aws'
        if self.logLevel == "DEBUG":
            self.logLevel = logging.DEBUG
        elif self.logLevel == "WARN":
            self.logLevel = logging.WARN
        elif self.logLevel == "INFO":
            self.logLevel = logging.INFO
        else:
            self.logLevel = logging.DEBUG
        if 'myself' not in self.actors:
            # Add myself as a known type
            self.actors['myself'] = {
                'type': self.aw_type,
                'factory': self.proto + self.fqdn + '/',
                'relationship': 'friend',  # associate, friend, partner, admin
            }
        # Dynamically load all the database modules
        self.DbActor = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_actor")
        self.DbPeerTrustee = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_peertrustee")
        self.DbProperty = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_property")
        self.DbAttribute = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_attribute")
        self.DbSubscription = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_subscription")
        self.DbSubscriptionDiff = importlib.import_module("actingweb" + ".db_" + self.database +
                                                          ".db_subscription_diff")
        self.DbTrust = importlib.import_module(
            "actingweb" + ".db_" + self.database + ".db_trust")
        self.module = {}
        if self.env == 'appengine':
            self.module["deferred"] = importlib.import_module(
                ".deferred", "google.appengine.api")
            self.module["urlfetch"] = importlib.import_module(
                ".urlfetch", "google.appengine.ext")
        else:
            self.module["deferred"] = None
            self.module["urlfetch"] = importlib.import_module("urlfetch")
        #########
        # ActingWeb settings for this app
        #########
        # This app follows the actingweb specification specified
        self.aw_version = "1.0"
        self.aw_supported = "www,oauth,callbacks,trust,onewaytrust,subscriptions," \
                            "actions,resources,methods,sessions,nestedproperties"  # This app supports these options
        # These are the supported formats
        self.aw_formats = "json"
        #########
        # Only touch the below if you know what you are doing
        #########
        if self.env == 'appengine':
            logging.getLogger().handlers[0].setLevel(
                self.logLevel)  # Hack to get access to GAE logger
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
        # root URI used to identity actor externally
        self.root = self.proto + self.fqdn + "/"
        # Authentication realm used in Basic auth
        self.auth_realm = self.fqdn

    @staticmethod
    def new_uuid(seed):
        return uuid.uuid5(uuid.NAMESPACE_URL, str(seed)).hex

    @staticmethod
    def new_token(length=40):
        tok = binascii.hexlify(os.urandom(int(length // 2)))
        return tok.decode('utf-8')
