=========
CHANGELOG
=========

v2.6.0: Aug 23, 2020
--------------------
- Add support for optional Basic authorisation in token request (e.g. Fitbit is requiring this)

v2.5.1: Jan 29, 2019
--------------------
- Move some annoying info messages to debug in auth/oauth
- Fix bug in set_attr for store where struct is not initialised (attribute.py:70)
- Enforce lower case on creator if @ (i.e. email) in value

v2.5.0: Nov 17, 2018
--------------------
- BREAKING: /www/properties template_values now return a dict with { 'key': value} instead of list of { 'name': 'key',
  'value': value}
- Add support for scope GET parameter in callback from OAUTH2 provider (useful for e.g. Google)
- Add support for oauth_extras dict in oauth config to set additional oauth paramters forwarded to OAUTH2 provider
  (Google uses this)
- Add support for dynamic:creator in oauth_extras to preset login hint etc when forwarding to OAuth2 auth endpoints
  (if creator==email, this allows you to send Google hint on which account to use with 'login_hint': 'dynamic:creator'
  in oauth_extras in config
- Add support for actor get_from_creator() to initialise an actor from a creator (only usable together with config
  variable unique_creator)
- Add support for get_properties(), delete_properties(), put_properties(), and post_properties in the on_aw() class.
  These allows on_aw overriding functions to process any old and new properties and return the resulting properties
  to be stored, deleted, or returned
- Move all internal (oauth_token, oauth_token_expiry, oauth_refresh_token, oauth_token_refresh_token_expiry,
  cookie_redirect, and trustee_root) data from properties (where they are exposed on GET /<actor_id>/properties) to internal
  variable store (attributes). Introduce config variable migrate_2_5_0 (default True) that will look for properties
  with oauth variable names if not found in internal store and move them over to internal store (should be turned
  off when all actors have migrated their oauth properties over to store)
- Add new interface InternalStore() (attribute.py) for storing and retrieving internal variables on an actor (i.e.
  attributes). All actors now have .store that can be used either as a dict or dot-notation. actor.store.var = 'this'
  or actor.store['var'] = 'this'. Set the variable to None to delete it. All variables are immediately stored to the
  database. Note that variable values must be json serializable
- Add new interface PropertyStore() (property.py) for storing and retrieving properties. Used just like InternalStore()
  and access through actor.property.my_var or actor.property['my_var']
- InternalStore(actor_id=None, config=None, bucket=None) can be used independently and the optional bucket parameter
  allows you to create an internal store that stores a set of variables in a specific bucket. A bucket is retrieved
  all at once and variables are written to database immediately
- Fix issue where downstream (trusts) server processing errors resulted in 405 instead of 500 error code
- Fix bug in oauth.put_request() where post was used instead of put
- Fix issue where 200 had Forbidden text

v2.4.3: Sep 27, 2018
--------------------
- Don't do relative import with import_module, AWS Lambda gets a hiccup

v2.4.2: Sep 27, 2018
--------------------
- Get rid of future requirement, just a pain

v2.4.1: Sep 26, 2018
--------------------
- Fix bad relative imports
- Use extras_require for future (python2 support)

v2.4.0: Sep 22 2018
--------------------
- Support python3

v2.3.0: Dec 27, 2017
--------------------
- Entire API for handlers and Actor() as well as other objects changed to be PEP8 compliant
- Add support for head_request(() in oauth and oauth_head() in auth
- Change all uses of now() to utcnow()
- db_gae for Google AppEngine is not kept updated, so folder deprecated and just kept for later reference
- Full linting/PEP8 review
- Add support for actor_id (set id) on Actor.create()

v2.2.2: Dec 3, 2017
-------------------
- Fix bug in region for properties and attributes resulting in using us-east-1 for these (and not us-west-1 as default)

v2.2.1: Dec 3, 2017
-------------------
- Add support for environment variable AWS_DB_PREFIX to support multiple actingweb tables in same DynamoDB region

v2.2.0: Nov 25, 2017
--------------------
- Add support for attribute.Attributes() and attribute.Buckets() (to be used for internal properties not exposed)
- Various bug fixes to make the oauth flows work

v2.1.2: Nov 12, 2017
--------------------
- Split out actingweb module as a separate pypi library and repository
- Python2 support, not python3
- Support AWS DynamoDB and Google Datastore in sub-modules
- Refactor out a set of handlers to allow easy integration into any web framework
- actingwebdemo as a full-functioning demo app to show how the library is used

Jul 9, 2017
--------------------
- Fix bug with unique actor setting and actor already exists
- Improve handling of enforce use of email property as creator
- Fix auth bug for callbacks (401 when no auth is expected)
- Add support for "lazy refresh" of oauth token, i.e. refresh if expired or refresh token has <24h to expiry
- Add support for Actors() class in actor.py to get a list of all actors with id and creator (ONLY for admin usage)
- Fix various bugs when subscriptions don't exist
- Improve logging when actor cannot be created

Apr 2, 2017
--------------------
- Changed license to BSD after approval from Cisco Systems
- Fix bug in deletion of trust relationship that would not delete subscription
- Add support for GET param ?refresh=true for web-based sessions to ignore set cookie and do oauth
- Fix bug in oauth.oauth_delete() returning success when >299 is returned from upstream

Mar 11, 2017
--------------------
- Fix bug in aw_actor_callbacks.py on does exist test after db refactoring
- Fix bug in handling of www/init form to set properties
- Add support to enforce that creator (in actor) is unique (Config.unique_creator bool)
- Add support to enforce that a creator field set to "creator" is overwritten if property "email" is set 
  (Config.force_email_prop_as_creator bool, default True). Note that username for basic login then changes from
  creator to the value of email property. 
  This functionality can be useful if actor is created by trustee and email is set later
- Add new DbActor.py function get_by_creator() to allow retrieving an actor based on the creator value


Feb 25, 2016
--------------------
- Major refactoring of all database code

  - All db entities are now accessible only from the actingweb/* libraries
  - Each entity can be accessed one by one (e.g. trust.py exposes trust class) and as a list (e.g. trust.py exposes trusts class)
  - actor_id and any parameters that identify the entity must be set when the class is instantiated
  - get() must be called on the object to retrieve it from the database and the object
    is returned as a dictionary
  - Subsequent calls to get() will return the dictionary without database access, but
    any changes will be synced to database immediately
  - The actingweb/* libraries do not contain any database-specific code, but imports
    a db library that exposes the barebone db operations per object
  - The google datastore code can be found in actingweb/db_gae
  - Each database entity has its own .py file exposing get(), modify(), create(), delete()
    and some additional search/utility functions where needed
  - These db classes do not do anything at init, and get() and create() must include all parameters
  - The database handles are kept in the object, so modify() and delete() require a get() or create()
    before they can be called
- Currently, Google Datastore is the only supported db backend, but the db_* code can now fairly
  easily be adapted to new databases

Nov 19, 2016
--------------------
- Create a better README in rst
- Add readthedocs.org support with conf.py and index.rst files
- Add the actingweb spec as an rst file
- Add a getting-started rst file
- Correct diff timestamps to UTC standard with T and Z notation
- Fix json issue where diff sub-structures are escaped
- Add 20 sec timeout on all urlfethc (inter-actor) communication
- Support using creator passphrase as bearer token IF creator username == trustee
  and passphrase has bitstrength > 80
- Added id, peerid, and subscriptionid in subscriptions to align with spec
- Add modiify() for actor to allow change of creator username
- Add support for /trust/trustee operations to align with spec
- Add /devtest path and config.devtest bool to allow test scripts
- Add /devtest testing of all aw_proxy functionality

Nov 17, 2016
--------------------
- Renaming of getPeer() and deletePeer() to get_peer_trustee() and delete_peer_trustee() to avoid confusion
- Support for oauth_put() (and corresponding put_request()) and fix to accept 404 without refreshing token
- aw_proxy support for get_resource(), change_resource((), and delete_resource(()
- Support PUT on /resources

Nov 5, 2016
--------------------
- Add support for getResources in aw_proxy.py
- Renamed peer to peerTrustee in peer.py to better reflect that it is created by actor as trustee

Nov 1, 2016
--------------
- Add support for change_resource(() and delete_resource(() in aw_proxy.py
- Add support for PUT to /resources and on_put_resources() in on_aw_resources.py

Oct 28, 2016
--------------
- Add support for establishment and tear-down of peer actors as trustee, actor.getPeer() and actor.deletePeer()

  - Add new db storage for peers created as trustee
  - Add new config.actor section in config.py to define known possible peers
- Add new actor support function: getTrustRelationshipByType()
- Add new AwProxy() class with helper functions to do RPCish peer operations on trust relationships

  - Either use trust_target or peer_target to send commands to a specific trust or to the trust associated with a peer (i.e. peer created by this app as a trustee)
  - Support for create_resource() (POST on remote actor path like /resources or /properties)
- Fix bug where clean up of actor did not delete remote subscription (actor.delete())

  - Add remoteSubscription deletion in aw-actor-subscription.py
  - Fix auth issue in aw-actor-callbacks.py revealed by ths bug

Oct 26, 2016
--------------
- Add support for trustee by adding trustee_root to actor factory
- Add debug logging in auth process
- Fix bug where actors created within the same second got the same id

Oct 15, 2016
--------------
- Added support for requests to /bot and a bot (permanent) token in config.py to do API requests
  without going through the /<actorid>/ paths. Used to support scenarios where users can communicate with a bot to
  initiate creation of an actor (or to do commands that don't need personal oauth authorization.

Oct 12, 2016
--------------
- Support for actor.get_from_property(property-name, value) to initialse an actor from db by looking up a property value
  (it must be unique)

Oct 9, 2016
--------------
- Added support for GET, PUT, and DELETE for any sub-level of /properties, 
  also below resource, i.e. /properties/<subtarget>/<resource>/something/andmore/...
- Fixed bug where blob='', i.e. deletion, would not be registered

Oct 7, 2016
--------------
- Added support for resource (in addition to target and subtarget) in subscriptions, thus allowing subscriptions to
  e.g. /resources/files/<fileid> (where <fileid> is the resource to subscribe to. /properties/subtarget/resource
  subscriptions are also allowed.

Oct 6, 2016
--------------
- Added support for /resources with on_aw_resources.py in on_aw/ to hook into GET, DELETE, and POST requests to /resources
- Added fixes for box.com specific OAUTH implementation
- Added new function oauth_get(), oauth_post(), and oauth_delete() to Auth() class. These will refresh a token if necessary and
  can be used insted of oauth.get_request(), post_request(), and delete_request(()
- Minor refactoring of inner workings of auth.py and oauth.py wrt return values and error codes

Sep 25, 2016
--------------
- Added use_cache=False to all db operations to avoid cache issue when there are multiple instances of same app in gae

Sep 4, 2016
--------------
- Refactoring of creation of trust:
  - ensure that secret is generated by initiating peer
  - ensure that a peer cannot have more than one relationship
  - ensure that a secret can only be used for one relationship

Aug 28, 2016
--------------
- Major refactoring of auth.py. Only affects how init_actingweb() is used, see function docs

Aug 21, 2016: New features
--------------------------
- Removed the possibility of setting a secret when initiating a new relationship, as well as ability to change secret. This is to avoid the possibility of detecting existing secrets (from other peers) by testing secrets

Aug 15, 2016: Bug fixes
------------------------
- Added new acl["approved"] flag to auth.py indicating whether an authenticated peer has been approved
- Added new parameter to the authorise() function to turn off the requirement that peer has been approved to allow access
- Changed default relationship to the lowest level (associate) and turned off default approval of the default relationship
- Added a new authorisation check to subscriptions to make sure that only peers with access to a path are allowed to subscribe to those paths
- Added a new approval in trust to allow non-approved peers to delete their relationship (in case they want to "withdraw" their relationship request)
- Fixed uncaught json exception in create_remote_subscription()
- Fixed possibility of subpath being None instead of '' in auth.py
- Fixed handling of both bool json type and string bool value for approved parameter for trust relationships


Aug 6, 2016: New features
----------------------------
- Support for deleting remote subscription (i.e. callback and subscription, dependent on direction) when an actor is
  deleted

  - New delete_remote_subscription() in actor.py
  - Added deletion to actor.delete()
  - New handler for DELETE of /callbacks in aw-actor-callbacks.py
  - New on_delete_callbacks() in on_aw_callbacks.py

Aug 6, 2016: Bug fixes
----------------------------
- Fixed bug where /meta/nonexistent resulted in 500

Aug 3, 2016: New features
----------------------------
- Support for doing callbacks when registering diffs

  - New function in actor.py: callback_subscription()
  - Added defer of callbacks to avoid stalling responses when adding diffs
  - Added new function get_trust_relationship() to get one specific relationship based on peerid (instead of searching using get_trust_relationships())
- Improved diff registration

  - Totally rewrote register_diffs() to register diffs for subscriptions that are not exact matches (i.e. broader/higher-level and more specific)
  - Added debug logging to trace how diffs are registered
- Owner-based access only to /callbacks/subscriptions
- Support for handling callbacks for subscriptions

  - New function in on_aw_callbacks.py: on_post_subscriptions() for handling callbacks on subscriptions
  - Changed aw-actor-callbacks.py to handle POSTs to /callbacks/subscriptions and forward those to on_post_subscriptions()

Aug 3, 2016: Bug fixes
----------------------------
- Added no cache to the rest of subscriptionDiffs DB operations to make sure that deferred subscription callbacks don't mess up sequencing
- Changed meta/raml to meta/specification to allow any type of specification language

Aug 1, 2016: New features
----------------------------
- Added support for GET on subscriptions as peer, generic register diffs function, as well as adding diffs when changing /properties. Also added support for creator initiating creation of a subscription by distingushing on POST to /subscriptions (as creator to inititate a subscription with another peer) and to /subscriptions/<peerid> (as peer to create subscription)
- Subscription is also created when initiating a remote subscription (using callback bool to set flag to identify a subscription where callback is expected). Still missing support for sending callbacks (high/low/none), as well as processing callbacks
- Added support for sequence number in subscription, so that missing diffs can be detected. Specific diffs can be retrieved by doing GET as peer on /subscriptions/<peerid>/<subid>/<seqnr> (and the diff will be cleared)

Jul 27, 2016: New features
----------------------------
- Started adding log statements to classes and methods
- Added this file to track changes
- Added support for requesting creation of subscriptions, GETing (with search) all subscriptions as creator (not peer), as well as deletion of subscriptions when an actor is deleted (still remaining GET all relationship as peer, GET on relationship to get diffs, DELETE subscription as peer, as well as mechanism to store diffs)

Jul 27, 2016: Bug fixes
----------------------------
- Changed all ndb.fetch() calls to not include a max item number
- Cleaned up actor delete() to go directly on database to delete all relevant items
- Fixed a bug where the requested peer would not store the requesting actor's mini-app type in db (in trust)
- Added use_cache=False in all trust.py ndb calls to get rid of the cache issues experienced when two different threads communicate to set up a trust
- Added a new check and return message when secret is not included in an "establish trust" request (requestor must always include secret)

July 12, 2016: New features
----------------------------
- config.py cleaned up a bit

July 12, 2016: Bug fixes
----------------------------
- Fix in on_aw_oauth_success where token can optionally supplied (first time oauth was done the token has not been flushed to db)
- Fix in on_aw_oauth_success where login attempt with wrong Spark user did not clear the cookie_redirect variable
- Fixed issue with wrong Content-Type header for GET and DELETE messages without json body
