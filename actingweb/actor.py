from __future__ import absolute_import
from builtins import str
from builtins import object
import datetime
import base64
from . import property
import json
from . import trust
from . import subscription
import logging
from . import peertrustee
from . import attribute


class Actor(object):

    ###################
    # Basic operations
    ###################

    def __init__(self, actor_id=None, config=None):
        self.config = config
        self.property_list = None
        self.subs_list = None
        self.actor = None
        self.passphrase = None
        self.creator = None
        self.last_response_code = 0
        self.last_response_message = ''
        self.id = actor_id
        self.handle = self.config.DbActor.DbActor()
        self.get(actor_id=actor_id)

    def get_peer_info(self,  url):
        # type: (res) -> dict()
        """Contacts an another actor over http/s to retrieve meta information."""
        try:
            logging.debug('Getting peer info at url(' + url + ')')
            if self.config.env == "appengine":
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
            response = self.config.module["urlfetch"].fetch(url=url + '/meta')
            res = {
                "last_response_code": response.status_code,
                "last_response_message": response.content,
                "data": json.loads(response.content.decode('utf-8', 'ignore')),
            }
            logging.debug('Got peer info from url(' + url +
                          ') with body(' + str(response.content) + ')')
        except (TypeError, ValueError, KeyError):
            res = {
                "last_response_code": 500,
            }
        return res

    def get(self, actor_id=None):
        """Retrieves an actor from storage or initialises if it does not exist."""
        if not actor_id and not self.id:
            return None
        elif not actor_id:
            actor_id = self.id
        if self.handle and self.actor and len(self.actor) > 0:
            return self.actor
        self.actor = self.handle.get(actor_id=actor_id)
        if self.actor and len(self.actor) > 0:
            self.id = self.actor["id"]
            self.creator = self.actor["creator"]
            self.passphrase = self.actor["passphrase"]
            if self.config.force_email_prop_as_creator:
                em = self.get_property("email").value
                if em and len(em) > 0:
                    self.modify(creator=em)
        else:
            self.id = None
            self.creator = None
            self.passphrase = None
        return self.actor

    def get_from_property(self, name='oauthId', value=None):
        """ Initialise an actor by matching on a stored property.

        Use with caution as the property's value de-facto becomes
        a security token. If multiple properties are found with the
        same value, no actor will be initialised.
        Also note that this is a costly operation as all properties
        of this type will be retrieved and proceessed.
        """
        actor_id = property.Property(name=name, value=value, config=self.config).get_actor_id()
        if not actor_id:
            self.id = None
            self.creator = None
            self.passphrase = None
            return
        self.get(actor_id=actor_id)

    def create(self, url, creator, passphrase, actor_id=None, delete=False):
        """"Creates a new actor and persists it.

            If delete is True, any existing actors with same creator value
            will be deleted. If it is False, the one with the correct passphrase
            will be chosen (if any)
        """
        seed = url
        now = datetime.datetime.utcnow()
        seed += now.strftime("%Y%m%dT%H%M%S%f")
        if len(creator) > 0:
            self.creator = creator
        else:
            self.creator = "creator"
        if self.config.unique_creator:
            in_db = self.config.DbActor.DbActor()
            exists = in_db.get_by_creator(creator=self.creator)
            if exists:
                # If uniqueness is turned on at a later point, we may have multiple accounts
                # with creator as "creator". Check if we have a property "email" and then
                # set creator to the email address.
                if delete:
                    for c in exists:
                        anactor = Actor(actor_id=c["id"], config=self.config)
                        anactor.delete()
                else:
                    if self.config.force_email_prop_as_creator and self.creator == "creator":
                        for c in exists:
                            anactor = Actor(actor_id=c["id"])
                            em = anactor.get_property("email").value
                            if em and len(em) > 0:
                                anactor.modify(creator=em)
                    for c in exists:
                        if c['passphrase'] == passphrase:
                            self.handle = in_db
                            self.id = c['id']
                            self.passphrase = c['passphrase']
                            self.creator = c['creator']
                            return True
                        return False
        if passphrase and len(passphrase) > 0:
            self.passphrase = passphrase
        else:
            self.passphrase = self.config.new_token()
        if actor_id:
            self.id = actor_id
        else:
            self.id = self.config.new_uuid(seed)
        if not self.handle:
            self.handle = self.config.DbActor.DbActor()
        self.handle.create(creator=self.creator,
                           passphrase=self.passphrase,
                           actor_id=self.id)
        return True

    def modify(self, creator=None):
        if not self.handle or not creator:
            logging.debug("Attempted modify of actor with no handle or no param changed")
            return False
        self.creator = creator
        if self.actor:
            self.actor["creator"] = creator
        self.handle.modify(creator=creator)
        return True

    def delete(self):
        """Deletes an actor and cleans up all relevant stored data"""
        if not self.handle:
            logging.debug("Attempted delete of actor with no handle")
            return False
        self.delete_peer_trustee(shorttype='*')
        if not self.property_list:
            self.property_list = property.Properties(actor_id=self.id, config=self.config)
        self.property_list.delete()
        subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
        subs.fetch()
        subs.delete()
        trusts = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trusts.fetch()
        for rel in relationships:
            self.delete_reciprocal_trust(peerid=rel["peerid"], delete_peer=True)
        trusts.delete()
        buckets = attribute.Buckets(actor_id=self.id, config=self.config)
        buckets.delete()
        self.handle.delete()

    ######################
    # Advanced operations
    ######################

    def set_property(self, name, value):
        """Sets an actor's property name to value."""
        prop = property.Property(self.id, name, config=self.config)
        prop.set(value)

    def get_property(self, name):
        """Retrieves a property object named name."""
        prop = property.Property(self.id, name, config=self.config)
        return prop

    def delete_property(self, name):
        """Deletes a property name."""
        prop = property.Property(self.id, name, config=self.config)
        prop.delete()

    def delete_properties(self):
        """Deletes all properties."""
        if not self.property_list:
            self.property_list = property.Properties(actor_id=self.id, config=self.config)
        return self.property_list.delete()

    def get_properties(self):
        """Retrieves properties from db and returns a dict."""
        self.property_list = property.Properties(actor_id=self.id, config=self.config)
        return self.property_list.fetch()

    def delete_peer_trustee(self, shorttype=None, peerid=None):
        if not peerid and not shorttype:
            return False
        if shorttype == '*':
            for t in self.config.actors:
                self.delete_peer_trustee(shorttype=t)
            return True
        if shorttype and not self.config.actors[shorttype]:
            logging.error('Got a request to delete an unknown actor type(' + shorttype + ')')
            return False
        peer_data = None
        new_peer = None
        if peerid:
            new_peer = peertrustee.PeerTrustee(actor_id=self.id, peerid=peerid, config=self.config)
            peer_data = new_peer.get()
            if not peer_data or len(peer_data) == 0:
                return False
        elif shorttype:
            new_peer = peertrustee.PeerTrustee(actor_id=self.id, short_type=shorttype, config=self.config)
            peer_data = new_peer.get()
            if not peer_data or len(peer_data) == 0:
                return False
        logging.debug(
            'Deleting peer actor at baseuri(' + peer_data["baseuri"] + ')')
        u_p = b'trustee:' + peer_data["passphrase"].encode('utf-8')
        headers = {'Authorization': 'Basic ' +
                   base64.b64encode(u_p).decode('utf-8'),
                   }
        try:
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=peer_data["baseuri"],
                                                                method=self.config.module["urlfetch"].DELETE,
                                                                headers=headers
                                                                )
            else:
                response = self.config.module["urlfetch"].delete(url=peer_data["baseuri"], headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except (self.config.module["urlfetch"].UrlfetchException,
                self.config.module["urlfetch"].URLError,
                self.config.module["urlfetch"].Timeout,
                self.config.module["urlfetch"].TooManyRedirects):
            logging.debug('Not able to delete peer actor remotely')
            self.last_response_code = 408
            return False
        if response.status_code < 200 or response.status_code > 299:
            logging.debug('Not able to delete peer actor remotely')
            return False
        # Delete trust, peer is already deleted remotely
        if not self.delete_reciprocal_trust(peerid=peer_data["peerid"], delete_peer=False):
            logging.debug('Not able to delete peer actor trust in db')
        if not new_peer.delete():
            logging.debug('Not able to delete peer actor in db')
            return False
        return True

    def get_peer_trustee(self, shorttype=None, peerid=None):
        """ Get a peer, either existing or create it as trustee 

        Will retrieve an existing peer or create a new and establish trust.
        If no trust exists, a new trust will be established.
        Use either peerid to target a specific known peer, or shorttype to
        allow creation of a new peer if none exists
        """
        if not peerid and not shorttype:
            return None
        if shorttype and not self.config.actors[shorttype]:
            logging.error('Got a request to create an unknown actor type(' + shorttype + ')')
            return None
        if peerid:
            new_peer = peertrustee.PeerTrustee(actor_id=self.id, peerid=peerid, config=self.config)
        else:
            new_peer = peertrustee.PeerTrustee(actor_id=self.id, short_type=shorttype, config=self.config)
        peer_data = new_peer.get()
        if peer_data and len(peer_data) > 0:
            logging.debug('Found peer in getPeer, now checking existing trust...')
            dbtrust = trust.Trust(actor_id=self.id, peerid=peer_data["peerid"], config=self.config)
            new_trust = dbtrust.get()
            if new_trust and len(new_trust) > 0:
                return peer_data
            logging.debug('Did not find existing trust, will create a new one')
        factory = self.config.actors[shorttype]['factory']
        # If peer did not exist, create it as trustee
        if not peer_data or len(peer_data) == 0:
            if len(factory) == 0:
                logging.error('Peer actor of shorttype(' + 
                              shorttype + ') does not have factory set.')
            params = {
                'creator': 'trustee',
                'trustee_root': self.config.root + self.id
            }
            data = json.dumps(params)
            logging.debug(
                'Creating peer actor at factory(' + factory + ') with data(' +
                str(data) + ')')
            response = None
            try:
                if self.config.env == 'appengine':
                    self.config.module["urlfetch"].set_default_fetch_deadline(20)
                    response = self.config.module["urlfetch"].fetch(url=factory,
                                                                    method=self.config.module["urlfetch"].POST,
                                                                    payload=data
                                                                    )
                else:
                    response = self.config.module["urlfetch"].post(
                        url=factory,
                        data=data,
                        headers={
                            'Content-Type': 'application/json'
                        }
                    )
                self.last_response_code = response.status_code
                self.last_response_message = response.content
            except (self.config.module["urlfetch"].UrlfetchException,
                    self.config.module["urlfetch"].URLError,
                    self.config.module["urlfetch"].Timeout,
                    self.config.module["urlfetch"].TooManyRedirects):
                logging.debug('Not able to create new peer actor')
                self.last_response_code = 408
            logging.debug('Create peer actor POST response:' + str(self.last_response_code))
            if self.last_response_code < 200 or self.last_response_code > 299:
                return None
            try:
                data = json.loads(response.content.decode('utf-8', 'ignore'))
            except (TypeError, ValueError, KeyError):
                logging.warning("Not able to parse response when creating peer at factory(" +
                                factory + ")")
                return None
            if 'Location' in response.headers:
                baseuri = response.headers['Location']
            elif 'location' in response.headers:
                baseuri = response.headers['location']
            else:
                logging.warning("No location uri found in response when creating a peer as trustee")
                baseuri = ""
            res = self.get_peer_info(baseuri)
            if not res or res["last_response_code"] < 200 or res["last_response_code"] >= 300:
                return None
            info_peer = res['data']
            if not info_peer or ('id' in info_peer and not info_peer["id"])\
                    or ('type' in info_peer and not info_peer["type"]):
                logging.info(
                    'Received invalid peer info when trying to create peer actor at: ' + str(factory))
                return None
            new_peer = peertrustee.PeerTrustee(actor_id=self.id, peerid=info_peer["id"], peer_type=info_peer["type"],
                                               config=self.config)
            if not new_peer.create(baseuri=baseuri, passphrase=data["passphrase"]):
                logging.error('Failed to create in db new peer Actor(' +
                              self.id + ') at ' + baseuri)
                return None
        # Now peer exists, create trust
        new_peer_data = new_peer.get()
        new_trust = self.create_reciprocal_trust(
                        url=new_peer_data["baseuri"],
                        secret=self.config.new_token(),
                        desc='Trust from trustee to ' + shorttype,
                        relationship=self.config.actors[shorttype]['relationship']
                        )
        if not new_trust or len(new_trust) == 0:
            logging.warning("Not able to establish trust relationship with peer at factory(" +
                            factory + ")")
        else:
            # Approve the relationship
            params = {
                'approved': True,
            }
            u_p = b'trustee:' + new_peer_data["passphrase"].encode('utf-8')
            headers = {'Authorization': 'Basic ' +
                       base64.b64encode(u_p).decode('utf-8'),
                       'Content-Type': 'application/json',
                       }
            data = json.dumps(params)
            try:
                if self.config.env == 'appengine':
                    self.config.module["urlfetch"].set_default_fetch_deadline(20)
                    response = self.config.module["urlfetch"].fetch(url=new_peer_data["baseuri"] +
                                                                    '/trust/' +
                                                                    self.config.actors[shorttype]['relationship'] +
                                                                    '/' + self.id,
                                                                    method=self.config.module["urlfetch"].PUT,
                                                                    payload=data,
                                                                    headers=headers
                                                                    )
                else:
                    response = self.config.module["urlfetch"].put(
                        url=new_peer_data["baseuri"] + '/trust/' + self.config.actors[shorttype]['relationship'] +
                        '/' + self.id, data=data, headers=headers)
                self.last_response_code = response.status_code
                self.last_response_message = response.content
            except (self.config.module["urlfetch"].UrlfetchException,
                    self.config.module["urlfetch"].URLError,
                    self.config.module["urlfetch"].Timeout,
                    self.config.module["urlfetch"].TooManyRedirects):
                self.last_response_code = 408
                self.last_response_message = 'Not able to approve peer actor trust remotely'
            if self.last_response_code < 200 or self.last_response_code > 299:
                logging.debug('Not able to delete peer actor remotely')
        return new_peer_data

    def get_trust_relationship(self, peerid=None):
        if not peerid:
            return None
        return trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()

    def get_trust_relationships(self, relationship='', peerid='', trust_type=''):
        """Retrieves all trust relationships or filtered."""
        trust_list = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trust_list.fetch()
        rels = []
        for rel in relationships:
            if len(relationship) > 0 and relationship != rel["relationship"]:
                continue
            if len(peerid) > 0 and peerid != rel["peerid"]:
                continue
            if len(trust_type) > 0 and trust_type != rel["type"]:
                continue
            rels.append(rel)
        return rels

    def modify_trust_and_notify(self, 
                                relationship=None, 
                                peerid=None, 
                                baseuri='', 
                                secret='', 
                                desc='', 
                                approved=None, 
                                verified=None, 
                                verification_token=None, 
                                peer_approved=None):
        """Changes a trust relationship and noties the peer if approval is changed."""
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid)
        if not relationships:
            return False
        this_trust = relationships[0]
        headers = dict()
        # If we change approval status, send the changed status to our peer
        if approved is True and this_trust["approved"] is False:
            params = {
                'approved': True,
            }
            requrl = this_trust["baseuri"] + '/trust/' + relationship + '/' + self.id
            if this_trust["secret"]:
                headers = {'Authorization': 'Bearer ' + this_trust["secret"],
                           'Content-Type': 'application/json',
                           }
            data = json.dumps(params)
            # Note the POST here instead of PUT. POST is used to used to notify about
            # state change in the relationship (i.e. not change the object as PUT
            # would do)
            logging.debug(
                'Trust relationship has been approved, notifying peer at url(' + requrl + ')')
            try:
                if self.config.env == 'appengine':
                    self.config.module["urlfetch"].set_default_fetch_deadline(20)
                    response = self.config.module["urlfetch"].fetch(url=requrl,
                                                                    method=self.config.module["urlfetch"].POST,
                                                                    payload=data,
                                                                    headers=headers
                                                                    )
                else:
                    response = self.config.module["urlfetch"].post(
                        url=requrl,
                        data=data,
                        headers=headers
                        )
                self.last_response_code = response.status_code
                self.last_response_message = response.content
            except (self.config.module["urlfetch"].UrlfetchException,
                    self.config.module["urlfetch"].URLError,
                    self.config.module["urlfetch"].Timeout,
                    self.config.module["urlfetch"].TooManyRedirects):
                logging.debug('Not able to notify peer at url(' + requrl + ')')
                self.last_response_code = 500
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        return dbtrust.modify(baseuri=baseuri,
                              secret=secret,
                              desc=desc,
                              approved=approved,
                              verified=verified,
                              verification_token=verification_token,
                              peer_approved=peer_approved
                              )

    def create_reciprocal_trust(self, url, secret=None, desc='', relationship='', trust_type=''):
        """Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor."""
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False
        res = self.get_peer_info(url)
        if not res or res["last_response_code"] < 200 or res["last_response_code"] >= 300:
            return False
        peer = res["data"]
        if not peer["id"] or not peer["type"] or len(peer["type"]) == 0:
            logging.info(
                "Received invalid peer info when trying to establish trust: " + url)
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logging.info(
                    "Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship
        # Create trust, so that peer can do a verify on the relationship (using
        # verification_token) when we request the relationship
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(baseuri=url, secret=secret, peer_type=peer["type"],
                              relationship=relationship, approved=True,
                              verified=False, desc=desc):
            logging.warning("Trying to establish a new Reciprocal trust when peer relationship already exists (" +
                            peer["id"] + ")")
            return False
        # Since we are initiating the relationship, we implicitly approve it
        # It is not verified until the peer has verified us
        new_trust = dbtrust.get()
        params = {
            'baseuri': self.config.root + self.id,
            'id': self.id,
            'type': self.config.aw_type,
            'secret': secret,
            'desc': desc,
            'verify': new_trust["verification_token"],
        }
        requrl = url + '/trust/' + relationship
        data = json.dumps(params)
        logging.debug('Creating reciprocal trust at url(' +
                      requrl + ') and body (' + str(data) + ')')
        try:
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=requrl,
                                                                method=self.config.module["urlfetch"].POST,
                                                                payload=data,
                                                                headers={
                                                                    'Content-Type': 'application/json', }
                                                                )
            else:
                response = self.config.module["urlfetch"].post(
                    url=requrl,
                    data=data,
                    headers={
                        'Content-Type': 'application/json', }
                    )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except (self.config.module["urlfetch"].UrlfetchException,
                self.config.module["urlfetch"].URLError,
                self.config.module["urlfetch"].Timeout,
                self.config.module["urlfetch"].TooManyRedirects):
            logging.debug(
                "Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logging.error(
                    "Couldn't find trust relationship after peer POST and verification")
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                # Do it direct on the trust (and not self.modifyTrustAndNotify) to avoid a callback
                # to the peer
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logging.debug(
                "Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False

    def create_verified_trust(self, baseuri='', peerid=None, approved=False,
                              secret=None, verification_token=None, trust_type=None,
                              peer_approved=None, relationship=None, desc=''):
        """Creates a new trust when requested and call backs to initiating actor to verify relationship."""
        if not peerid or len(baseuri) == 0 or not relationship:
            return False
        requrl = baseuri + '/trust/' + relationship + '/' + self.id
        if not secret or len(secret) == 0:
            logging.debug('No secret received from requesting peer(' + peerid +
                          ') at url (' + requrl + '). Verification is not possible.')
            verified = False
        else:
            headers = {'Authorization': 'Bearer ' + secret,
                       }
            logging.debug('Verifying trust at requesting peer(' + peerid +
                          ') at url (' + requrl + ') and secret(' + secret + ')')
            try:
                if self.config.env == 'appengine':
                    self.config.module["urlfetch"].set_default_fetch_deadline(20)
                    response = self.config.module["urlfetch"].fetch(url=requrl,
                                                                    method=self.config.module["urlfetch"].GET,
                                                                    headers=headers)
                else:
                    response = self.config.module["urlfetch"].get(url=requrl, headers=headers)
                self.last_response_code = response.status_code
                self.last_response_message = response.content
                try:
                    logging.debug(
                        'Verifying trust response JSON:' + str(response.content))
                    data = json.loads(response.content.decode('utf-8', 'ignore'))
                    if data["verification_token"] == verification_token:
                        verified = True
                    else:
                        verified = False
                except ValueError:
                    logging.debug(
                        'No json body in response when verifying trust at url(' + requrl + ')')
                    verified = False
            except (self.config.module["urlfetch"].UrlfetchException,
                    self.config.module["urlfetch"].URLError,
                    self.config.module["urlfetch"].Timeout,
                    self.config.module["urlfetch"].TooManyRedirects):
                logging.debug(
                    'No response when verifying trust at url' + requrl + ')')
                verified = False
        new_trust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        if not new_trust.create(baseuri=baseuri, secret=secret, peer_type=trust_type, approved=approved, 
                                peer_approved=peer_approved,
                                relationship=relationship, verified=verified, desc=desc):
            return False
        else:
            return new_trust.get()

    def delete_reciprocal_trust(self, peerid=None, delete_peer=False):
        """Deletes a trust relationship and requests deletion of peer's relationship as well."""
        failed_once = False  # For multiple relationships, this will be True if at least one deletion at peer failed
        success_once = False  # True if at least one relationship was deleted at peer
        if not peerid:
            rels = self.get_trust_relationships()
        else:
            rels = self.get_trust_relationships(peerid=peerid)
        for rel in rels:
            if delete_peer:
                url = rel["baseuri"] + '/trust/' + rel["relationship"] + '/' + self.id
                headers = {}
                if rel["secret"]:
                    headers = {'Authorization': 'Bearer ' + rel["secret"],
                               }
                logging.debug(
                    'Deleting reciprocal relationship at url(' + url + ')')
                try:
                    if self.config.env == 'appengine':
                        self.config.module["urlfetch"].set_default_fetch_deadline(20)
                        response = self.config.module["urlfetch"].fetch(url=url,
                                                                        method=self.config.module["urlfetch"].DELETE,
                                                                        headers=headers)
                    else:
                        response = self.config.module["urlfetch"].delete(url=url, headers=headers)
                except (self.config.module["urlfetch"].UrlfetchException,
                        self.config.module["urlfetch"].URLError,
                        self.config.module["urlfetch"].Timeout,
                        self.config.module["urlfetch"].TooManyRedirects):
                    logging.debug(
                        'Failed to delete reciprocal relationship at url(' + url + ')')
                    failed_once = True
                    continue
                if (response.status_code < 200 or response.status_code > 299) and response.status_code != 404:
                    logging.debug(
                        'Failed to delete reciprocal relationship at url(' + url + ')')
                    failed_once = True
                    continue
                else:
                    success_once = True
            if not self.subs_list:
                self.subs_list = subscription.Subscriptions(actor_id=self.id, config=self.config).fetch()
            # Delete this peer's subscriptions
            for sub in self.subs_list:
                if sub["peerid"] == rel["peerid"]:
                    logging.debug("Deleting subscription(" + sub["subscriptionid"] + ") as part of trust deletion.")
                    sub_obj = self.get_subscription_obj(peerid=sub["peerid"], subid=sub["subscriptionid"],
                                                        callback=sub["callback"])
                    sub_obj.delete()
            dbtrust = trust.Trust(actor_id=self.id, peerid=rel["peerid"], config=self.config)
            dbtrust.delete()
        if delete_peer and (not success_once or failed_once):
            return False
        return True

    def create_subscription(self, peerid=None, target=None, subtarget=None, resource=None, granularity=None,
                            subid=None, callback=False):
        new_sub = subscription.Subscription(
            actor_id=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)
        new_sub.create(target=target, subtarget=subtarget, resource=resource,
                       granularity=granularity)
        return new_sub.get()

    def create_remote_subscription(self, peerid=None, target=None, subtarget=None, resource=None, granularity=None):
        """Creates a new subscription at peerid."""
        if not peerid or not target:
            return False
        relationships = self.get_trust_relationships(peerid=peerid)
        if not relationships:
            return False
        peer = relationships[0]
        params = {
            'id': self.id,
            'target': target,
        }
        if subtarget:
            params['subtarget'] = subtarget
        if resource:
            params['resource'] = resource
        if granularity and len(granularity) > 0:
            params['granularity'] = granularity
        requrl = peer["baseuri"] + '/subscriptions/' + self.id
        data = json.dumps(params)
        headers = {'Authorization': 'Bearer ' + peer["secret"],
                   'Content-Type': 'application/json',
                   }
        try:
            logging.debug('Creating remote subscription at url(' +
                          requrl + ') with body (' + str(data) + ')')
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=requrl,
                                                                method=self.config.module["urlfetch"].POST,
                                                                payload=data,
                                                                headers=headers
                                                                )
            else:
                response = self.config.module["urlfetch"].post(url=requrl, data=data, headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except (self.config.module["urlfetch"].UrlfetchException,
                self.config.module["urlfetch"].URLError,
                self.config.module["urlfetch"].Timeout,
                self.config.module["urlfetch"].TooManyRedirects):
            return None
        try:
            logging.debug('Created remote subscription at url(' + requrl +
                          ') and got JSON response (' + str(response.content) + ')')
            data = json.loads(response.content.decode('utf-8', 'ignore'))
        except ValueError:
            return None
        if 'subscriptionid' in data:
            subid = data["subscriptionid"]
        else:
            return None
        if self.last_response_code == 201:
            self.create_subscription(peerid=peerid, target=target,
                                     subtarget=subtarget, resource=resource, granularity=granularity, subid=subid, 
                                     callback=True)
            if 'Location' in response.headers:
                return response.headers['Location']
            elif 'location' in response.headers:
                return response.headers['location']
        else:
            return None

    def get_subscriptions(self, peerid=None, target=None, subtarget=None, resource=None, callback=False):
        """Retrieves subscriptions from db."""
        if not self.id:
            return None
        if not self.subs_list:
            self.subs_list = subscription.Subscriptions(actor_id=self.id, config=self.config).fetch()
        ret = []
        for sub in self.subs_list:
            if not peerid or (peerid and sub["peerid"] == peerid):
                if not target or (target and sub["target"] == target):
                    if not subtarget or (subtarget and sub["subtarget"] == subtarget):
                        if not resource or (resource and sub["resource"] == resource):
                            if not callback or (callback and sub["callback"] == callback):
                                ret.append(sub)
        return ret

    def get_subscription(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config).get()

    def get_subscription_obj(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)

    def delete_remote_subscription(self, peerid=None, subid=None):
        if not subid or not peerid:
            return False
        trust_rel = self.get_trust_relationship(peerid=peerid)
        if not trust_rel:
            return False
        sub = self.get_subscription(peerid=peerid, subid=subid)
        if not sub:
            sub = self.get_subscription(peerid=peerid, subid=subid, callback=True)
        if 'callback' not in sub or not sub["callback"]:
            url = trust_rel["baseuri"] + '/subscriptions/' + self.id + '/' + subid
        else:
            url = trust_rel["baseuri"] + '/callbacks/subscriptions/' + self.id + '/' + subid
        headers = {'Authorization': 'Bearer ' + trust_rel["secret"],
                   }
        try:
            logging.debug('Deleting remote subscription at url(' + url + ')')
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=url,
                                                                method=self.config.module["urlfetch"].DELETE,
                                                                headers=headers)
            else:
                response = self.config.module["urlfetch"].delete(url=url, headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
            if response.status_code == 204:
                return True
            else:
                logging.debug(
                    'Failed to delete remote subscription at url(' + url + ')')
                return False
        except (self.config.module["urlfetch"].UrlfetchException,
                self.config.module["urlfetch"].URLError,
                self.config.module["urlfetch"].Timeout,
                self.config.module["urlfetch"].TooManyRedirects):
            return False

    def delete_subscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False
        sub = subscription.Subscription(
            actor_id=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)
        return sub.delete()

    def callback_subscription(self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None):
        if not peerid or not diff or not sub or not blob:
            logging.warning("Missing parameters in callbackSubscription")
            return
        if "granularity" in sub and sub["granularity"] == "none":
            return
        trust_rel = self.get_trust_relationship(peerid)
        if not trust_rel:
            return
        params = {
            'id': self.id,
            'subscriptionid': sub["subscriptionid"],
            'target': sub["target"],
            'sequence': diff["sequence"],
            'timestamp': str(diff["timestamp"]),
            'granularity': sub["granularity"],
        }
        if sub["subtarget"]:
            params['subtarget'] = sub["subtarget"]
        if sub["resource"]:
            params['resource'] = sub["resource"]
        if sub["granularity"] == "high":
            try:
                params['data'] = json.loads(blob)
            except (TypeError, ValueError, KeyError):
                params['data'] = blob
        if sub["granularity"] == "low":
            params['url'] = self.config.root + self.id + '/subscriptions/' + \
                trust_rel["peerid"] + '/' + sub["subscriptionid"] + '/' + str(diff["sequence"])
        requrl = trust_rel["baseuri"] + '/callbacks/subscriptions/' + self.id + '/' + sub["subscriptionid"]
        data = json.dumps(params)
        headers = {'Authorization': 'Bearer ' + trust_rel["secret"],
                   'Content-Type': 'application/json',
                   }
        try:
            logging.debug('Doing a callback on subscription at url(' +
                          requrl + ') with body(' + str(data) + ')')
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=requrl,
                                                                method=self.config.module["urlfetch"].POST,
                                                                payload=data.encode('utf-8'),
                                                                headers=headers
                                                                )
            else:
                response = self.config.module["urlfetch"].post(
                    url=requrl,
                    data=data.encode('utf-8'),
                    headers=headers
                    )
        except (self.config.module["urlfetch"].UrlfetchException,
                self.config.module["urlfetch"].URLError,
                self.config.module["urlfetch"].Timeout,
                self.config.module["urlfetch"].TooManyRedirects):
            logging.debug(
                'Peer did not respond to callback on url(' + requrl + ')')
            self.last_response_code = 0
            self.last_response_message = 'No response from peer for subscription callback'
            return
        self.last_response_code = response.status_code
        self.last_response_message = response.content
        if response.status_code == 204 and sub["granularity"] == "high":
            if not sub_obj:
                logging.warning("About to clear diff without having subobj set")
            else:
                sub_obj.clear_diff(diff["sequence"])

    def register_diffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

            If resource is set, the blob is expected to be the FULL resource object, not a diff.
            """
        if blob is None or not target:
            return
        # Get all subscriptions, both with the specific subtarget/resource and those
        # without
        subs = self.get_subscriptions(
            target=target, subtarget=None, resource=None, callback=False)
        if not subs:
            subs = []
        if subtarget and resource:
            logging.debug("register_diffs() - blob(" + blob + "), target(" +
                          target + "), subtarget(" + subtarget + "), resource(" +
                          resource + "), # of subs(" + str(len(subs)) + ")")
        elif subtarget:
            logging.debug("register_diffs() - blob(" + blob + "), target(" +
                          target + "), subtarget(" + subtarget + 
                          "), # of subs(" + str(len(subs)) + ")")            
        else:
            logging.debug("register_diffs() - blob(" + blob + "), target(" +
                          target + "), # of subs(" + str(len(subs)) + ")")
        for sub in subs:
            # Skip the ones without correct subtarget
            if subtarget and sub["subtarget"] and sub["subtarget"] != subtarget:
                logging.debug("     - no match on subtarget, skipping...")
                continue
            # Skip the ones without correct resource
            if resource and sub["resource"] and sub["resource"] != resource:
                logging.debug("     - no match on resource, skipping...")
                continue
            sub_obj = self.get_subscription_obj(peerid=sub["peerid"], subid=sub["subscriptionid"])
            sub_obj_data = sub_obj.get()
            logging.debug("     - processing subscription(" + sub["subscriptionid"] +
                          ") for peer(" + sub["peerid"] + ") with target(" + 
                          sub_obj_data["target"] + ") subtarget(" + str(sub_obj_data["subtarget"] or '') +
                          ") and resource(" + str(sub_obj_data["resource"] or '') + ")")
            # Subscription with a resource, but this diff is on a higher level
            if (not resource or not subtarget) and sub_obj_data["subtarget"] and sub_obj_data["resource"]:
                # Create a json diff on the subpart that this subscription
                # covers
                try:
                    jsonblob = json.loads(blob)
                    if not subtarget:
                        subblob = json.dumps(jsonblob[sub_obj_data["subtarget"]][sub_obj_data["resource"]])
                    else:
                        subblob = json.dumps(jsonblob[sub_obj_data["resource"]])
                except (TypeError, ValueError, KeyError):
                    # The diff does not contain the resource
                    logging.debug("         - subscription has resource(" +
                                  sub_obj_data["resource"] + "), no matching blob found in diff")
                    continue
                logging.debug("         - subscription has resource(" +
                              sub_obj_data["resource"] + "), adding diff(" + subblob + ")")
                finblob = subblob
            # The diff is on the resource, but the subscription is on a 
            # higher level
            elif resource and not sub_obj_data["resource"]:
                # Since we have a resource, we know the blob is the entire resource, not a diff
                # If the subscription is for a sub-target, send [resource] = blob
                # If the subscription is for a target, send [subtarget][resource] = blob
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    if not sub_obj_data["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = jsonblob
                    else:
                        upblob[resource] = jsonblob
                except (TypeError, ValueError, KeyError):
                    if not sub_obj_data["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = blob
                    else:
                        upblob[resource] = blob
                finblob = json.dumps(upblob)
                logging.debug("         - diff has resource(" + resource +
                              "), subscription has not, adding diff(" + finblob + ")")
            # Subscriptions with subtarget, but this diff is on a higher level
            elif not subtarget and sub_obj_data["subtarget"]:
                # Create a json diff on the subpart that this subscription
                # covers
                subblob = None
                try:
                    jsonblob = json.loads(blob)
                    subblob = json.dumps(jsonblob[sub_obj_data["subtarget"]])
                except (TypeError, ValueError, KeyError):
                    # The diff blob does not contain the subtarget
                    pass
                logging.debug("         - subscription has subtarget(" +
                              sub_obj_data["subtarget"] + "), adding diff(" + subblob + ")")
                finblob = subblob
            # The diff is on the subtarget, but the subscription is on the
            # higher level
            elif subtarget and not sub_obj_data["subtarget"]:
                # Create a data["subtarget"] = blob diff to give correct level
                # of diff to subscriber
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    upblob[subtarget] = jsonblob
                except (TypeError, ValueError, KeyError):
                    upblob[subtarget] = blob
                finblob = json.dumps(upblob)
                logging.debug("         - diff has subtarget(" + subtarget +
                              "), subscription has not, adding diff(" + finblob + ")")
            else:
                # The diff is correct for the subscription
                logging.debug(
                              "         - exact target/subtarget match, adding diff(" + blob + ")")
                finblob = blob
            diff = sub_obj.add_diff(blob=finblob)
            if not diff:
                logging.warning("Failed when registering a diff to subscription (" +
                                sub["subscriptionid"] + "). Will not send callback.")
            else:
                if self.config.module["deferred"]:
                    self.config.module["deferred"].defer(self.callback_subscription, peerid=sub["peerid"],
                                                         sub_obj=sub_obj,
                                                         sub=sub_obj_data, diff=diff, blob=finblob)
                else:
                    self.callback_subscription(peerid=sub["peerid"], sub_obj=sub_obj,
                                               sub=sub_obj_data, diff=diff, blob=finblob)


class Actors(object):
    """ Handles all actors
    """

    def fetch(self):
        if not self.list:
            return False
        if self.actors is not None:
            return self.actors
        self.actors = self.list.fetch()
        return self.actors

    def __init__(self, config=None):
        self.config = config
        self.list = self.config.DbActor.DbActorList()
        self.actors = None
        self.fetch()
