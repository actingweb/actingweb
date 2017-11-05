import datetime
import base64
import property
import json
import trust
import subscription
import logging
import peertrustee

class actor():

    ###################
    # Basic operations
    ###################

    def __init__(self, id=None, config=None):
        self.config = config
        self.property_list = None
        self.subs_list = None
        self.actor = None
        self.passphrase = None
        self.creator = None
        self.id = id
        self.handle = self.config.db_actor.db_actor()
        self.get(id=id)

    def getPeerInfo(self,  url):
        """Contacts an another actor over http/s to retrieve meta information."""
        try:
            logging.debug('Getting peer info at url(' + url + ')')
            if self.config.env == "appengine":
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
            response = self.config.module["urlfetch"].fetch(url=url + '/meta')
            res = {
                "last_response_code": response.status_code,
                "last_response_message": response.content,
                "data": json.loads(response.content),
            }
            logging.debug('Got peer info from url(' + url +
                          ') with body(' + response.content + ')')
        except:
            res = {
                "last_response_code": 500,
            }
        return res

    def get(self, id=None):
        """Retrieves an actor from storage or initialises if it does not exist."""
        if not id and not self.id:
            return None
        elif not id:
            id = self.id
        if self.handle and self.actor and len(self.actor) > 0:
            return self.actor
        self.actor = self.handle.get(actorId=id)
        if self.actor and len(self.actor) > 0:
            self.id = self.actor["id"]
            self.creator = self.actor["creator"]
            self.passphrase = self.actor["passphrase"]
            if self.config.force_email_prop_as_creator:
                em = self.getProperty("email").value
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
        actorId = property.property(name=name, value=value).getActorId()
        if not actorId:
            self.id = None
            self.creator = None
            self.passphrase = None
            return
        self.get(id=actorId)

    def create(self, url, creator, passphrase, delete=False):
        """"Creates a new actor and persists it.

            If delete is True, any existing actors with same creator value
            will be deleted. If it is False, the one with the correct passphrase
            will be chosen (if any)
        """
        seed = url
        now = datetime.datetime.now()
        seed += now.strftime("%Y%m%dT%H%M%S%f")
        if len(creator) > 0:
            self.creator = creator
        else:
            self.creator = "creator"
        if self.config.unique_creator:
            in_db = self.config.db_actor.db_actor()
            exists = in_db.getByCreator(creator=self.creator)
            if exists:
                # If uniqueness is turned on at a later point, we may have multiple accounts
                # with creator as "creator". Check if we have a property "email" and then
                # set creator to the email address.
                if delete:
                    for c in exists:
                        anactor = actor(id=c["id"])
                        anactor.delete()
                else:
                    if self.config.force_email_prop_as_creator and self.creator == "creator":
                        for c in exists:
                            anactor = actor(id=c["id"])
                            em = anactor.getProperty("email").value
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
            self.passphrase = self.config.newToken()
        self.id = self.config.newUUID(seed)
        if not self.handle:
            self.handle = self.config.db_actor.db_actor()
        self.handle.create(creator=self.creator,
                           passphrase=self.passphrase,
                           actorId=self.id)
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
        self.deletePeerTrustee(shorttype='*')
        if not self.property_list:
            self.property_list = property.properties(actorId=self.id, config=self.config)
        self.property_list.delete()
        subs = subscription.subscriptions(actorId=self.id, config=self.config)
        subs.fetch()
        subs.delete()
        trusts = trust.trusts(actorId=self.id, config=self.config)
        relationships = trusts.fetch()
        for rel in relationships:
            self.deleteReciprocalTrust(peerid=rel["peerid"], deletePeer=True)
        trusts.delete()
        self.handle.delete()

    ######################
    # Advanced operations
    ######################

    def setProperty(self, name, value):
        """Sets an actor's property name to value."""
        prop = property.property(self.id, name, config=self.config)
        prop.set(value)

    def getProperty(self, name):
        """Retrieves a property object named name."""
        prop = property.property(self.id, name, config=self.config)
        return prop

    def deleteProperty(self, name):
        """Deletes a property name."""
        prop = property.property(self.id, name, config=self.config)
        prop.delete()

    def deleteProperties(self):
        """Deletes all properties."""
        if not self.property_list:
            self.property_list = property.properties(actorId=self.id, config=self.config)
        return self.property_list.delete()

    def getProperties(self):
        """Retrieves properties from db and returns a dict."""
        self.property_list = property.properties(actorId=self.id, config=self.config)
        return self.property_list.fetch()

    def deletePeerTrustee(self, shorttype=None, peerid=None):
        if not peerid and not shorttype:
            return False
        if shorttype == '*':
            for t in self.config.actors:
                self.deletePeerTrustee(shorttype=t)
            return True
        if shorttype and not self.config.actors[shorttype]:
            logging.error('Got a request to delete an unknown actor type(' + shorttype + ')')
            return False
        if peerid:
            new_peer = peertrustee.peertrustee(actorId=self.id, peerid=peerid, config=self.config)
            peerData = new_peer.get()
            if not peerData or len(peerData) == 0:
                return False
        elif shorttype:
            new_peer = peertrustee.peertrustee(actorId=self.id, shorttype=shorttype, config=self.config)
            peerData = new_peer.get()
            if not peerData or len(peerData) == 0:
                return False
        logging.debug(
            'Deleting peer actor at baseuri(' + peerData["baseuri"] + ')')
        headers = {'Authorization': 'Basic ' +
                   base64.b64encode('trustee:' + peerData["passphrase"]),
                   }
        try:
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(url=peerData["baseuri"],
                                          method=self.config.module["urlfetch"].DELETE,
                                          headers=headers
                                          )
            else:
                response = self.config.module["urlfetch"].delete(url=peerData["baseuri"], headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except:
            logging.debug('Not able to delete peer actor remotely')
            self.last_response_code = 408
            return False
        if response.status_code < 200 or response.status_code > 299:
            logging.debug('Not able to delete peer actor remotely')
            return False
        # Delete trust, peer is already deleted remotely
        if not self.deleteReciprocalTrust(peerid=peerData["peerid"], deletePeer=False):
            logging.debug('Not able to delete peer actor trust in db')
        if not new_peer.delete():
            logging.debug('Not able to delete peer actor in db')
            return False
        return True

    def getPeerTrustee(self, shorttype=None, peerid=None):
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
            new_peer = peertrustee.peertrustee(actorId=self.id, peerid=peerid, config=self.config)
        else:
            new_peer = peertrustee.peertrustee(actorId=self.id, shorttype=shorttype, config=self.config)
        peerData = new_peer.get()
        if peerData and len(peerData) > 0:
            logging.debug('Found peer in getPeer, now checking existing trust...')
            db_trust = trust.trust(actorId=self.id, peerid=peerData["peerid"], config=self.config)
            new_trust = db_trust.get()
            if new_trust and len(new_trust) > 0:
                return peerData
            logging.debug('Did not find existing trust, will create a new one')
        factory = self.config.actors[shorttype]['factory']
        # If peer did not exist, create it as trustee
        if not peerData or len(peerData) == 0:
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
            except:
                logging.debug('Not able to create new peer actor')
                self.last_response_code = 408
            logging.debug('Create peer actor POST response:' + response.content)
            if response.status_code < 200 or response.status_code > 299:
                return None
            try:
                data = json.loads(response.content)
            except:
                logging.warn("Not able to parse response when creating peer at factory(" + 
                            factory + ")")
                return None
            if 'Location' in response.headers:
                baseuri = response.headers['Location']
            elif 'location' in response.headers:
                baseuri = response.headers['location']
            else:
                logging.warn("No location uri found in response when creating a peer as trustee")
                baseuri = ""
            res = self.getPeerInfo(baseuri)
            if not res or res["last_response_code"] < 200 or res["last_response_code"] >= 300:
                return None
            info = res["data"]
            if not info["id"] or not info["type"] or len(info["type"]) == 0:
                logging.info(
                    "Received invalid peer info when trying to create peer actor at: " + factory)
                return None
            new_peer = peertrustee.peertrustee(actorId=self.id, peerid=info["id"], type=info["type"], config=self.config)
            if not new_peer.create(baseuri=baseuri, passphrase=data["passphrase"]):
                logging.error('Failed to create in db new peer actor(' + 
                            peer["id"] + ') at ' + baseuri)
                return None
        # Now peer exists, create trust
        newPeerData = new_peer.get()
        new_trust = self.createReciprocalTrust(
                        url=newPeerData["baseuri"],
                        secret=self.config.newToken(),
                        desc='Trust from trustee to ' + shorttype,
                        relationship=self.config.actors[shorttype]['relationship']
                        )
        if not new_trust or len(new_trust) == 0:
            logging.warn("Not able to establish trust relationship with peer at factory(" +
                         factory + ")")
        else:
            # Approve the relationship
            params = {
                'approved': True,
            }
            headers = {'Authorization': 'Basic ' +
                       base64.b64encode('trustee:' + newPeerData["passphrase"]),
                       'Content-Type': 'application/json',
                       }
            data = json.dumps(params)
            try:
                if self.config.env == 'appengine':
                    self.config.module["urlfetch"].set_default_fetch_deadline(20)
                    response = self.config.module["urlfetch"].fetch(url=newPeerData["baseuri"] +
                                              '/trust/' +
                                              self.config.actors[shorttype]['relationship'] +
                                              '/' + self.id,
                                              method=self.config.module["urlfetch"].PUT,
                                              payload=data,
                                              headers=headers
                                              )
                else:
                    response = self.config.module["urlfetch"].put(
                        url=newPeerData["baseuri"] + '/trust/' + self.config.actors[shorttype]['relationship'] +
                        '/' + self.id, data=data, headers=headers)
                self.last_response_code = response.status_code
                self.last_response_message = response.content
            except:
                self.last_response_code = 408
                self.last_response_message = 'Not able to approve peer actor trust remotely'
            if response.status_code < 200 or response.status_code > 299:
                logging.debug('Not able to delete peer actor remotely')
        return newPeerData

    def getTrustRelationship(self, peerid=None):
        if not peerid:
            return None
        return trust.trust(actorId=self.id, peerid=peerid, config=self.config).get()

    def getTrustRelationships(self, relationship='', peerid='', type=''):
        """Retrieves all trust relationships or filtered."""
        list = trust.trusts(actorId=self.id, config=self.config)
        relationships = list.fetch()
        rels = []
        for rel in relationships:
            if len(relationship) > 0 and relationship != rel["relationship"]:
                continue
            if len(peerid) > 0 and peerid != rel["peerid"]:
                continue
            if len(type) > 0 and type != rel["type"]:
                continue
            rels.append(rel)
        return rels

    def modifyTrustAndNotify(self, relationship=None, peerid=None, baseuri='', secret='', desc='', approved=None, verified=None, verificationToken=None, peer_approved=None):
        """Changes a trust relationship and noties the peer if approval is changed."""
        if not relationship or not peerid:
            return False
        relationships = self.getTrustRelationships(
            relationship=relationship, peerid=peerid)
        if not relationships:
            return False
        this_trust = relationships[0]
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
            except:
                logging.debug('Not able to notify peer at url(' + requrl + ')')
                self.last_response_code = 500
        db_trust = trust.trust(actorId=self.id, peerid=peerid, config=self.config)
        return db_trust.modify(baseuri=baseuri,
                                       secret=secret,
                                       desc=desc,
                                       approved=approved,
                                       verified=verified,
                                       verificationToken=verificationToken,
                                       peer_approved=peer_approved)

    def createReciprocalTrust(self, url, secret=None, desc='', relationship='', type=''):
        """Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor."""
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False
        res = self.getPeerInfo(url)
        if not res or res["last_response_code"] < 200 or res["last_response_code"] >= 300:
            return False
        peer = res["data"]
        if not peer["id"] or not peer["type"] or len(peer["type"]) == 0:
            logging.info(
                "Received invalid peer info when trying to establish trust: " + url)
            return False
        if len(type) > 0:
            if type.lower() != peer["type"].lower():
                logging.info(
                    "Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship
        # Create trust, so that peer can do a verify on the relationship (using
        # verificationToken) when we request the relationship
        db_trust = trust.trust(actorId=self.id, peerid=peer["id"], config=self.config)
        if not db_trust.create(baseuri=url, secret=secret, type=peer["type"],
                         relationship=relationship, approved=True,
                         verified=False, desc=desc):
            logging.warn("Trying to establish a new Reciprocal trust when peer relationship already exists (" + peer["id"] + ")")
            return False
        # Since we are initiating the relationship, we implicitly approve it
        # It is not verified until the peer has verified us
        new_trust = db_trust.get()
        params = {
            'baseuri': self.config.root + self.id,
            'id': self.id,
            'type': self.config.type,
            'secret': secret,
            'desc': desc,
            'verify': new_trust["verificationToken"],
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
        except:
            logging.debug(
                "Not able to create trust with peer, deleting my trust.")
            db_trust.delete()
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.trust(actorId=self.id, peerid=peer["id"], config=self.config)
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
            db_trust.delete()
            return False

    def createVerifiedTrust(self, baseuri='', peerid=None, approved=False,
                            secret=None, verificationToken=None, type=None,
                            peer_approved=None, relationship=None, desc=''):
        """Creates a new trust when requested and call backs to initiating actor to verify relationship."""
        if not peerid or len(baseuri) == 0 or not relationship:
            return False
        requrl = baseuri + '/trust/' + relationship + '/' + self.id
        headers = {}
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
                        'Verifying trust response JSON:' + response.content)
                    data = json.loads(response.content)
                    if data["verificationToken"] == verificationToken:
                        verified = True
                    else:
                        verified = False
                except ValueError:
                    logging.debug(
                        'No json body in response when verifying trust at url(' + requrl + ')')
                    verified = False
            except:
                logging.debug(
                    'No response when verifying trust at url' + requrl + ')')
                verified = False
        new_trust = trust.trust(actorId=self.id, peerid=peerid, config=self.config)
        if not new_trust.create(baseuri=baseuri, secret=secret, type=type, approved=approved, peer_approved=peer_approved,
                                relationship=relationship, verified=verified, desc=desc):
            return False
        else:
            return new_trust.get()

    def deleteReciprocalTrust(self, peerid=None, deletePeer=False):
        """Deletes a trust relationship and requests deletion of peer's relationship as well."""
        failedOnce = False  # For multiple relationships, this will be True if at least one deletion at peer failed
        successOnce = False  # True if at least one relationship was deleted at peer
        if not peerid:
            rels = self.getTrustRelationships()
        else:
            rels = self.getTrustRelationships(peerid=peerid)
        for rel in rels:
            if deletePeer:
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
                except:
                    logging.debug(
                        'Failed to delete reciprocal relationship at url(' + url + ')')
                    failedOnce = True
                    continue
                if (response.status_code < 200 or response.status_code > 299) and response.status_code != 404:
                    logging.debug(
                        'Failed to delete reciprocal relationship at url(' + url + ')')
                    failedOnce = True
                    continue
                else:
                    successOnce = True
            if not self.subs_list:
                self.subs_list = subscription.subscriptions(actorId=self.id, config=self.config).fetch()
            # Delete this peer's subscriptions
            for sub in self.subs_list:
                if sub["peerid"] == rel["peerid"]:
                    logging.debug("Deleting subscription(" + sub["subscriptionid"] + ") as part of trust deletion.")
                    subObj = self.getSubscriptionObj(peerid=sub["peerid"], subid=sub["subscriptionid"], callback=sub["callback"])
                    subObj.delete()
            db_trust = trust.trust(actorId=self.id, peerid=rel["peerid"], config=self.config)
            db_trust.delete()
        if deletePeer and (not successOnce or failedOnce):
            return False
        return True

    def createSubscription(self, peerid=None, target=None, subtarget=None, resource=None, granularity=None, subid=None, callback=False):
        new_sub = subscription.subscription(
            actorId=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)
        new_sub.create(target=target, subtarget=subtarget, resource=resource,
                       granularity=granularity)
        return new_sub.get()

    def createRemoteSubscription(self, peerid=None, target=None, subtarget=None, resource=None, granularity=None):
        """Creates a new subscription at peerid."""
        if not peerid or not target:
            return False
        relationships = self.getTrustRelationships(peerid=peerid)
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
        except:
            return None
        try:
            logging.debug('Created remote subscription at url(' + requrl +
                          ') and got JSON response (' + response.content + ')')
            data = json.loads(response.content)
        except ValueError:
            return None
        if 'subscriptionid' in data:
            subid = data["subscriptionid"]
        else:
            return None
        if self.last_response_code == 201:
            self.createSubscription(peerid=peerid, target=target,
                                    subtarget=subtarget, resource=resource, granularity=granularity, subid=subid, callback=True)
            if 'Location' in response.headers:
                return response.headers['Location']
            elif 'location' in response.headers:
                return response.headers['location']
        else:
            return None

    def getSubscriptions(self, peerid=None, target=None, subtarget=None, resource=None, callback=False):
        """Retrieves subscriptions from db."""
        if not self.id:
            return None
        if not self.subs_list:
            self.subs_list = subscription.subscriptions(actorId=self.id, config=self.config).fetch()
        ret = []
        for sub in self.subs_list:
            if not peerid or (peerid and sub["peerid"] == peerid):
                if not target or (target and sub["target"] == target):
                    if not subtarget or (subtarget and sub["subtarget"] == subtarget):
                        if not resource or (resource and sub["resource"] == resource):
                            if not callback or (callback and sub["callback"] == callback):
                                ret.append(sub)
        return ret

    def getSubscription(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.subscription(
            actorId=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config).get()

    def getSubscriptionObj(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.subscription(
            actorId=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)

    def deleteRemoteSubscription(self, peerid=None, subid=None):
        if not subid or not peerid:
            return False
        trust = self.getTrustRelationship(peerid=peerid)
        if not trust:
            return False
        sub = self.getSubscription(peerid=peerid, subid=subid)
        if not sub:
            sub = self.getSubscription(peerid=peerid, subid=subid, callback=True)
        if 'callback' not in sub or not sub["callback"]:
            url = trust["baseuri"] + '/subscriptions/' + self.id + '/' + subid
        else:
            url = trust["baseuri"] + '/callbacks/subscriptions/' + self.id + '/' + subid
        headers = {'Authorization': 'Bearer ' + trust["secret"],
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
        except:
            return False

    def deleteSubscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False
        sub = subscription.subscription(
            actorId=self.id, peerid=peerid, subid=subid, callback=callback, config=self.config)
        return sub.delete()

    def callbackSubscription(self, peerid=None, subObj=None, sub=None, diff=None, blob=None):
        if not peerid or not diff or not sub or not blob:
            logging.warn("Missing parameters in callbackSubscription")
            return
        if "granularity" in sub and sub["granularity"] == "none":
            return
        trust = self.getTrustRelationship(peerid)
        if not trust:
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
            except:
                params['data'] = blob
        if sub["granularity"] == "low":
            params['url'] = self.config.root + self.id + '/subscriptions/' + \
                trust["peerid"] + '/' + sub["subscriptionid"] + '/' + str(diff["sequence"])
        requrl = trust["baseuri"] + '/callbacks/subscriptions/' + self.id + '/' + sub["subscriptionid"]
        data = json.dumps(params)
        headers = {'Authorization': 'Bearer ' + trust["secret"],
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
        except:
            logging.debug(
                'Peer did not respond to callback on url(' + requrl + ')')
            self.last_response_code = 0
            self.last_response_message = 'No response from peer for subscription callback'
            return
        self.last_response_code = response.status_code
        self.last_response_message = response.content
        if response.status_code == 204 and sub["granularity"] == "high":
            if not subObj:
                logging.warn("About to clear diff without having subobj set")
            else:
                subObj.clearDiff(diff["sequence"])

    def registerDiffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

            If resource is set, the blob is expected to be the FULL resource object, not a diff.
            """
        if blob is None or not target:
            return
        # Get all subscriptions, both with the specific subtarget/resource and those
        # without
        subs = self.getSubscriptions(
            target=target, subtarget=None, resource=None, callback=False)
        if not subs:
            subs = []
        if subtarget and resource:
            logging.debug("registerDiffs() - blob(" + blob + "), target(" +
                          target + "), subtarget(" + subtarget + "), resource(" +
                          resource + "), # of subs(" + str(len(subs)) + ")")
        elif subtarget:
            logging.debug("registerDiffs() - blob(" + blob + "), target(" +
                          target + "), subtarget(" + subtarget + 
                          "), # of subs(" + str(len(subs)) + ")")            
        else:
            logging.debug("registerDiffs() - blob(" + blob + "), target(" +
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
            subObj = self.getSubscriptionObj(peerid=sub["peerid"], subid=sub["subscriptionid"])
            subObjData = subObj.get()
            logging.debug("     - processing subscription(" + sub["subscriptionid"] +
                          ") for peer(" + sub["peerid"] + ") with target(" + 
                          subObjData["target"] + ") subtarget(" + str(subObjData["subtarget"] or '') +
                          ") and resource(" + str(subObjData["resource"] or '') + ")")
            finblob = None
            # Subscription with a resource, but this diff is on a higher level
            if (not resource or not subtarget) and subObjData["subtarget"] and subObjData["resource"]:
                # Create a json diff on the subpart that this subscription
                # covers
                try:
                    jsonblob = json.loads(blob)
                    if not subtarget:
                        subblob = json.dumps(jsonblob[subObjData["subtarget"]][subObjData["resource"]])
                    else:
                        subblob = json.dumps(jsonblob[subObjData["resource"]])
                except:
                    # The diff does not contain the resource
                    subblob = None
                    logging.debug("         - subscription has resource(" +
                                  subObjData["resource"] + "), no matching blob found in diff")
                    continue
                logging.debug("         - subscription has resource(" +
                              subObjData["resource"] + "), adding diff(" + subblob + ")")
                finblob = subblob
            # The diff is on the resource, but the subscription is on a 
            # higher level
            elif resource and not subObjData["resource"]:
                # Since we have a resource, we know the blob is the entire resource, not a diff
                # If the subscription is for a sub-target, send [resource] = blob
                # If the subscription is for a target, send [subtarget][resource] = blob
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    if not subObjData["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = jsonblob
                    else:
                        upblob[resource] = jsonblob
                except:
                    if not subObjData["subtarget"]:
                        upblob[subtarget] = {}
                        upblob[subtarget][resource] = blob
                    else:
                        upblob[resource] = blob
                finblob = json.dumps(upblob)
                logging.debug("         - diff has resource(" + resource +
                              "), subscription has not, adding diff(" + finblob + ")")
            # Subscriptions with subtarget, but this diff is on a higher level
            elif not subtarget and subObjData["subtarget"]:
                # Create a json diff on the subpart that this subscription
                # covers
                try:
                    jsonblob = json.loads(blob)
                    subblob = json.dumps(jsonblob[subObjData["subtarget"]])
                except:
                    # The diff blob does not contain the subtarget
                    subblob = None
                    continue
                logging.debug("         - subscription has subtarget(" +
                              subObjData["subtarget"] + "), adding diff(" + subblob + ")")
                finblob = subblob
            # The diff is on the subtarget, but the subscription is on the
            # higher level
            elif subtarget and not subObjData["subtarget"]:
                # Create a data["subtarget"] = blob diff to give correct level
                # of diff to subscriber
                upblob = {}
                try:
                    jsonblob = json.loads(blob)
                    upblob[subtarget] = jsonblob
                except:
                    upblob[subtarget] = blob
                finblob = json.dumps(upblob)
                logging.debug("         - diff has subtarget(" + subtarget +
                              "), subscription has not, adding diff(" + finblob + ")")
            else:
                # The diff is correct for the subscription
                logging.debug(
                              "         - exact target/subtarget match, adding diff(" + blob + ")")
                finblob = blob
            diff = subObj.addDiff(blob=finblob)
            if not diff:
                logging.warn("Failed when registering a diff to subscription (" +
                             sub["subscriptionid"] + "). Will not send callback.")
            else:
                if self.config.module["deferred"]:
                    deferred.defer(self.callbackSubscription, peerid=sub["peerid"], subObj=subObj,
                               sub=subObjData, diff=diff, blob=finblob)
                else:
                    self.callbackSubscription(peerid = sub["peerid"], subObj = subObj,
                    sub = subObjData, diff = diff, blob = finblob)

class actors():
    """ Handles all actors
    """

    def fetch(self):
        if not self.list:
            return False
        if self.actors is not None:
            return self.actors
        self.actors = self.list.fetch()
        return self.actors

    def __init__(self, filter=None, config=None):
        self.config = config
        self.list = self.config.db_actor.db_actor_list()
        self.actors = None
        self.fetch()
