======================================================
README - actingweb - an ActingWeb Library
======================================================
This is a python library implementation showcasing the REST-based `ActingWeb <http://actingweb.org>`_
distributed micro-services model. A typical use case is bot to bot communication on a peer to peer level.
It serves as the reference implementation for the ActingWeb REST protocol
specification <http://actingweb.readthedocs.io/en/release/actingweb-spec.html>`_ for
how such micro-services interact.

Building and installing
------------------------

::

# Build source distribution
python setup.py sdist

# Build a binary distribution for python2:
python setup.py bdist_wheel

# Upload to test server:
python setup.py sdist upload -r pypitest

# Upload to production server:
twine upload dist/*


Repository and documentation
----------------------------

The library is available as a PYPI library and installed with `pip install actingweb`. Project home is at
`https://pypi.org/project/actingweb/ <https://pypi.org/project/actingweb/>`_.

The git repository for this library can be found at
`https://bitbucket.org/gregerw/actingweb <https://bitbucket.org/gregerw/actingweb>`_.

The latest documentation for the released version (release branch) of this library can be found at 
`http://actingweb.readthedocs.io/ <http://actingweb.readthedocs.io/>`_.

The master branch of the library has the latest features and bug fixes and the updated documentation can be found at
`http://actingweb.readthedocs.io/en/master <http://actingweb.readthedocs.io/en/master>`_.


Why use actingweb?
---------------------
ActingWeb is well suited for applications where each individual user's data and functionality both needs high degree
of security and privacy AND high degree of interactions with the outside world. Typical use cases are Internet of Things
where each user's "Thing" becomes a bot that interacts with the outside world, as well as bot to bot
communication where each user can get a dedicated, controllable bot talking to other user's bots.

As a developer, you get a set of out of the box functionality from the ActingWeb library:

- an out-of-the-box REST bot representing each user's thing, service, or functionality (your choice)
- a way to store and expose data over REST in a very granular way using properties
- a trust system that allows creation of relationships the user's bot on the user level
- a subscription system that allows one bot (user) to subscribe to another bot's (user's) changes
- an oauth framework to tie the bot to any other API service and thus allow user to user communication using
    individual user's data from the API service

There is a high degree of configurability in what to expose, and although the ActingWeb specification specifies
a protocol set to allow bots from different developers to talk to each other, not all functionality needs to be
exposed.`

Each user's indvidual bot is called an ``actor`` and this actor has its own root URL where its data and services are
exposed. See below for further details.

Features of actingweb library
----------------------------------
The latest code in master is at all times deployed to
`https://actingwebdemo.greger.io/ <https://actingwebdemo.greger.io/>`_
It has implemented a simple sign-up page as a front-end to a REST-based factory URL that will instantiate a
new actor with a guid to identify the actor. The guid is then embedded in the actor's root URL, e.g.
``https://actingwebdemo.greger.io/9f1c331a3e3b5cf38d4c3600a2ab5d54``.

If you try to create an actor, you will get to a simple web front-end where you can set the actor's data
(properties) and delete the actor. You can later access the actor (both /www and REST) by using the Creator
you set as username and the passphrase you get when creating the actor and log in.

**acting-web-gae-library** is a close to complete implementation of the full ActingWeb specification where all
functionality can be accessed through the actor's root URL (e.g.
``https://actingwebdemo.greger.io/9f1c331a3e3b5cf38d4c3600a2ab5d54``):

- ``/properties``: attributed/value pairs as flat or nested json can be set, accessed, and deleted to store this actor's data
- ``/meta``: a publicly available json structure allowing actor's to discover each other's capabilities
- ``/trust``: access to requesting, approving, and managing trust relationships with other actors of either the same type or any other actor "talking actingweb"
- ``/subscriptions``: once a trust relationship is set up, this path allows access to establishing, retrieving, and managing subscriptions that are based on paths and identified with target, sub-target, and resource, e.g. ``/resources/folders/12345``
- ``/callbacks``: used for verification when establishing trust/subscriptions, to receive callbacks on subscriptions, as well as a programming hook to process webhooks from 3rd party services
- ``/resources``: a skeleton to simplify exposure of any type of resource (where /properties is not suited)
- ``/oauth``: used to initiate a www-based oauth flow to tie the actor to a specific OAuth user and service. Available if OAuth is turned on and a 3rd party OAuth service has been configured in config.py. /www will also be redirected to /oauth (*OAuth is not enabled in the online actingwebdemo mini-application*)

**Sidenote**: The **actingweb  library** also implements a simple mechanism for protecting the /www path with oauth
(not in the specification). On successful OAuth authorisation, it will set a browser cookie to the oauth
token. This is not used in the inline demo and requires also that the identity of the user authorising OAuth
access is the same user already tied to the instantiated actor. There is a programming hook that allows such
verification as part of the OAuth flow, but it is not enabled in the actingwebdemo mini-application.

Other applications using the actingweb library
---------------------------------------------------
There is also another demo application available for `Cisco Spark <http://www.ciscospark.com>`_
. It uses the actingweb library to implement a Cisco Spark bot and integration. If you have signed up as a
Cisco Spark user, you can try it out by sending a message to armyknife@sparkbot.io.

More details about the Spark Army Knife can be found on `this blog <http://stuff.ttwedel.no/tag/spark>`_
.

The ActingWeb Model
-------------------
The ActingWeb micro-services model and protocol defines a bot-to-bot and micro-service-to-micro-service
communication that allows extreme distribution of data and functionality. This makes it very suitable for
holding small pieces of sensitive data on behalf of a user or "things" (as in Internet of Things).
These sensitive data can then be used and shared in a very granular and controlled way through the secure
and distributed ActingWeb REST protocol. This allows you to expose e.g. your location data from your phone
directly on the Internet (protected by a security framework) and to be used by other services **on your choosing**.
You can at any time revoke access to your data for one particular service without influencing anything else.

The ActingWeb Micro-Services Model
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The programming model in ActingWeb is based on an extreme focus on only representing one small set of functionality
and for only one user or entity. This is achieved by not allowing any other way of calling the service
(in ActingWeb called a "mini-application") than through a user and the mini-app's REST interface (a user's
instance of a mini-application is called an *actor* in ActingWeb). From a practical point of view, getting xyz's
location through the REST protocol is as simple as doing a GET ``http://mini-app-url/xyz/properties/location``.

There is absolutely no way of getting xyz's and yyz's location information in one request, and the security model
enforces access based on user (i.e. actor), so even if you have access to
``http://mini-app-url/xyz/properties/location``, you may not have access to
``http://mini-app-url/yyz/properties/location``.

Any functionality desired across actors, for example xyz sharing location information with yyz
**MUST** be done through the ActingWeb REST protocol. However, since the ActingWeb service-to-service
REST protocol is standardised, **any** service implementing the protocol can easily share data with other services.

The ActingWeb REST Protocol
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The ActingWeb REST protocol specifies a set of default endpoints (like ``/properties``, ``/trust``,
``/subscriptions`` etc) that are used to implement the service-to-service communication, as well as a set of
suggested endpoints (like ``/resources``, ``/actions`` etc) where the mini-applications can expose their own
functionality. All exchanges are based on REST principles and a set of flows are built into the protocol that
support exchanging data, establishing trust between actors (per actor, not per mini-application), as well as
subscribing to changes.

The ActingWeb Security Model
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The security model is based on trust between actors, not mini-applications. This means that each instance of the
mini-application holding the sensitive data for one particular person or thing **must** be connected through a trust
relationship to another ActingWeb actor, but it doesn't have to be a mini-application of the same type (like location
sharing), but could be a location sharing actor establishing a trust relationship with 911 authorities to
allow emergency services to always be able to look you up.

There are currently two ways of establishing trust between actors: either through an explicit OAuth flow where an
actor is tied to somebody's account somewhere else (like Google, Box.com, etc) or through a flow where one actor
requests a trust relationship with another, which then needs to be approved either interactively by a user or
programatically through the REST interface.

See `http://actingweb.org/ <http://actingweb.org/>`_ for more information.


