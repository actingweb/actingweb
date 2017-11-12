Getting Started
===============

The easiest way to get started is to start out with the actingwebdemo application
`http://actingweb.readthedocs.io/ <http://actingweb.readthedocs.io/>`_.

It uses the webapp2 framework to set up the REST endpoints that the ActingWeb library uses to expose
the bot functionality.

If you want to use flask or any other framework, that is also easy, you just need to set up the routing between the
endpoints and call the right request handlers in the library.

For each endpoint, you need to:

- map the incoming route to your own handler and catch the necessary variables
- in your handler, set up an aw_web_request object and copy in the request's data using the chosen web framework
- call the right ActingWeb handler
- copy over the results to your chosen web framework

Webapp2 Example
----------------

With Webapp2, this is done the following way using the /<actor-id>/properties endpoint as an example:

Set up route
+++++++++++++


```python
webapp2.Route(r'/<id>/properties<:/?><name:(.*)>', actor_properties.actor_properties)
```

Here, id and name are captured as variables.

Handle the request like Webapp2 requires
+++++++++++++++++++++++++++++++++++++++++

```python
from actingweb import aw_web_request
from actingweb.handlers import properties

import webapp2

class actor_properties(webapp2.RequestHandler):

    def init(self):
        self.obj=aw_web_request.aw_webobj(
            url=self.request.url,
            params=self.request.params,
            body=self.request.body,
            headers=self.request.headers)
        self.handler = properties.properties_handler(self.obj, self.app.registry.get('config'))

    def get(self, id, name):
        self.init()
        # Process the request
        self.handler.get(id, name)
        # Pass results back to webapp2
        self.response.set_status(self.obj.response.status_code, self.obj.response.status_message)
        self.response.headers = self.obj.response.headers
        self.response.write(self.obj.response.body)

...
```

Here, the actor_properties is the handler as specified by Webapp2 where the get method is called by the framework.
First thing it does is to initialize the request using the init() method. This method basically does two things:
Instantiates an aw_web_request object with the Webapp2 request data, and then it creates an actingweb handler using
the new object and an instance of the actingweb config object.

Once that is done, the self.handler.get() method can be called, passing in the two variables from the URL.

Finally, Webapp2 response is set using the output data from the aw_web_request object.

For /properties, other methods must also be set up (put, post, and delete).

Config Object
-------------

In order to set the configuration, an instance of the config object should be passed into the actingweb handler.

Here's how to instantiate it:`

```python
        config = config.config(
            database='dynamodb',
            fqdn="actingwebdemo.greger.io",
            proto="http://")
```


All Configuration Variables and Their Defaults
----------------------------------------------

```python
# Basic settings for this app
fqdn = "actingwebdemo-dev.appspot.com"  # The host and domain, i.e. FQDN, of the URL
proto = "https://"  # http or https
database = 'dynamodb'                          # 'dynamodb' or 'gae' for Google Datastore
ui = True                                      # Turn on the /www path
devtest = True                                 # Enable /devtest path for test purposes, MUST be False in production
unique_creator = False                          # Will enforce unique creator field across all actors
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

# If myself is not found in actors, the myself actor is added:
actors['myself'] = {
    'type': type,
    'factory': proto + fqdn + '/',
    'relationship': 'friend',  # associate, friend, partner, admin
}
```

Tailoring behaviour on requests
--------------------------------

The on_aw module implements a base class with a set of methods that will be called on certain actions.
For example, requests to /bot can and should be handled by the application outside actingweb.

> The /bot path can be used
> to handle requests to the mini-application, for example to create a new actor or create a trust relationship between
> two actors, or just to handle incoming requests that don't use the actor's id in the URL, but where the actor can be
> identified through the POST data.``

To make your own bot handler, make you own instance inheriting the on_aw_base class and override the correct method.

```python
from actingweb import on_aw

class my_aw(on_aw.on_aw_base()):

    def bot_post(self, path):
        # Do stuff with posts to the bot
```