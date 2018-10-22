Getting Started
===============

The easiest way to get started is to start out with the actingwebdemo mini-application
`http://acting-web-demo.readthedocs.io/ <http://acting-web-demo.readthedocs.io/>`_.

It uses the Flask framework to set up all the REST endpoints that the ActingWeb library exposes, and pretty much
the entire specification.

If you want to use  another framework, that is  easy, the application.py shows how this is done for Flask.


How it works
----------------
An ActingWeb mini-application exposes an endpoint to create a new actor representing one instance on behalf of one
person or entity. This could for example be the location of a mobile phone, and the app is thus a location app.
The ActingWeb actor representing one mobile phones location can be reached on https://app-url.a-domain.io/actor-id and
all the ActingWeb endpoints to get the location, subscribe to location updates and so on can be found below this
actor root URL.

Below is an example of how the trust endpoint is exposed in the demo app.
The same code here handles all the three different ways the trust endpoint can be invoked (to create a new trust
relationship between two actors or change it). The Flask code maps these URL patterns and invokes the app_trust()
function. In Handler, the Flask request is parsed and simplified into a dictionary that can be easily passed to the
ActingWeb framework. The process() function is then invoked with the right parameters and finally get_response()
is used to map the ActingWeb response into a Flask response.

Some endpoints can return template variables to be used in a rendered web output. The variables can be found in
h.webobj.response.template_values and can easily be rendered with Jinja2 (Flask's template renderer) this way:
return render_template('aw-actor-www-root.html', **h.webobj.response.template_values)


::
    @app.route('/<actor_id>/trust', methods=['GET', 'POST', 'DELETE', 'PUT'], strict_slashes=False)
    @app.route('/<actor_id>/trust/<relationship>', methods=['GET', 'POST', 'DELETE', 'PUT'], strict_slashes=False)
    @app.route('/<actor_id>/trust/<relationship>/<peerid>', methods=['GET', 'POST', 'DELETE', 'PUT'], strict_slashes=False)
    def app_trust(actor_id, relationship=None, peerid=None):
        h = Handler(request)
        if peerid:
            if not h.process(actor_id=actor_id, relationship=relationship, peerid=peerid):
                return Response(status=404)
        elif relationship:
            if not h.process(actor_id=actor_id, relationship=relationship):
                return Response(status=404)
        else:
            if not h.process(actor_id=actor_id):
                return Response(status=404)
        return h.get_response()

Config Object
-------------

In order to set the configuration, the config function is used to return a config object that is
passed into the actingweb framework.

The ActingWebDemo app shows mostly empty values as placeholders where APP_HOST_FQDN is the only you must make sure
matches the domain where the app is hosted.



All Configuration Variables and Their Defaults
----------------------------------------------

::

    # Basic settings for this app
    fqdn = "actingwebdemo-dev.appspot.com"  # The host and domain, i.e. FQDN, of the URL
    proto = "https://"  # http or https
    database = 'dynamodb'                          # 'dynamodb', for future other databases supported
    ui = True                                      # Turn on the /www path
    devtest = True                                 # Enable /devtest path for test purposes, MUST be False in production
    unique_creator = False                         # Will enforce unique creator field across all actors
    force_email_prop_as_creator = True             # Use "email" property to set creator value (after creation and property set)
    www_auth = "basic"                             # basic or oauth: basic for creator + bearer tokens
    logLevel = "DEBUG"                             # Change to WARN for production, DEBUG for debugging, and INFO for normal testing

    # Configurable ActingWeb settings for this app
    type = "urn:actingweb:actingweb.org:gae-demo"  # The app type this actor implements
    desc = "GAE Demo actor: "                      # A human-readable description for this specific actor
    specification = ""                             # URL to a RAML/Swagger etc definition if available
    version = "1.0"                                # A version number for this app
    info = "http://actingweb.org/"                 # Where can more info be found

    # Trust settings for this app
    default_relationship = "associate"  # Default relationship if not specified
    auto_accept_default_relationship = False  # True if auto-approval

    # Known and trusted ActingWeb actors
    actors = {
        '<SHORTTYPE>': {
            'type': 'urn:<ACTINGWEB_TYPE>',
            'factory': '<ROOT_URI>',
            'relationship': 'friend',               # associate, friend, partner, admin
            },
    }

    # OAuth settings for this app, fill in if OAuth is used
    oauth = {
        'client_id': "",                                # An empty client_id turns off oauth capabilities
        'client_secret': "",
        'redirect_uri': proto + fqdn + "/oauth",
        'scope': "",
        'auth_uri': "",
        'token_uri': "",
        'response_type': "code",
        'grant_type': "authorization_code",
        'refresh_type': "refresh_token",
    }
    bot = {
        'token': '',
        'email': '',
    }

    # myself should be an actor if we want actors to have relationships with other actors of the same type
    actors['myself'] = {
        'type': type,
        'factory': proto + fqdn + '/',
        'relationship': 'friend',  # associate, friend, partner, admin
    }


Tailoring behaviour on requests
--------------------------------

The on_aw module implements a base class with a set of methods that will be called on certain actions.
For example, requests to /bot can and should be handled by the application outside actingweb.

|   > The /bot path can be used
|   > to handle requests to the mini-application, for example to create a new actor or create a trust relationship between
|   > two actors, or just to handle incoming requests that don't use the actor's id in the URL, but where the actor can be
|   > identified through the POST data.``

To make your own bot handler, make you own instance inheriting the on_aw_base class and override the correct method.

::

    from actingweb import on_aw

    class my_aw(on_aw.OnAWBase()):

        def bot_post(self, path):
            # Do stuff with posts to the bot
