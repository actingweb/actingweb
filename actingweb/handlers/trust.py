from builtins import str
import json
import logging

from actingweb import trust
from actingweb import auth
from actingweb.handlers import base_handler


# /trust aw_handlers
#
# GET /trust with query parameters (relationship, type, and peerid) to retrieve trust relationships (auth: only creator
# and admins allowed)
# POST /trust with json body to initiate a trust relationship between this
#   actor and another (reciprocal relationship) (auth: only creator and admins allowed)
# POST /trust/{relationship} with json body to create new trust
#   relationship (see config.py for default relationship and auto-accept, no
#   auth required)
# GET /trust/{relationship}}/{actorid} to get details on a specific relationship (auth: creator, admin, or peer secret)
# POST /trust/{relationship}}/{actorid} to send information to a peer about changes in the relationship
# PUT /trust/{relationship}}/{actorid} with a json body to change details on a relationship (baseuri, secret, desc)
# (auth: creator,
#   admin, or peer secret)
# DELETE /trust/{relationship}}/{actorid} to delete a relationship (with
#   ?peer=true if the delete is from the peer) (auth: creator, admin, or
#   peer secret)

# Handling requests to trust/
class TrustHandler(base_handler.BaseHandler):

    def get(self, actor_id):
        if self.request.get('_method') == 'POST':
            self.post(actor_id)
            return
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id, path='trust',
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='trust', method='GET'):
            self.response.set_status(403)
            return
        relationship = self.request.get('relationship')
        peer_type = self.request.get('type')
        peerid = self.request.get('peerid', )

        pairs = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid, trust_type=peer_type)
        if not pairs or len(pairs) == 0:
            self.response.set_status(404, 'Not found')
            return
        out = json.dumps(pairs)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')

    def post(self, actor_id):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id, path='trust',
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='trust', method='POST'):
            self.response.set_status(403)
            return
        desc = ''
        relationship = self.config.default_relationship
        peer_type = ''
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'url' in params:
                url = params['url']
            else:
                url = ''
            if 'relationship' in params:
                relationship = params['relationship']
            if 'type' in params:
                peer_type = params['type']
            if 'desc' in params:
                desc = params['desc']
        except ValueError:
            url = self.request.get('url')
            relationship = self.request.get('relationship')
            peer_type = self.request.get('type')
        if len(url) == 0:
            self.response.set_status(400, 'Missing peer URL')
            return
        secret = self.config.new_token()
        new_trust = myself.create_reciprocal_trust(
            url=url, secret=secret, desc=desc, relationship=relationship,
            trust_type=peer_type)
        if not new_trust:
            self.response.set_status(408, 'Unable to create trust relationship')
            return
        self.response.headers["Location"] = str(self.config.root +
                                                myself.id + '/trust/' +
                                                new_trust["relationship"] +
                                                '/' + new_trust["peerid"])
        out = json.dumps(new_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, 'Created')


# Handling requests to /trust/*, e.g. /trust/friend
class TrustRelationshipHandler(base_handler.BaseHandler):

    def get(self, actor_id, relationship):
        if self.request.get('_method') == 'POST':
            self.post(actor_id, relationship)
            return
        self.response.set_status(404, "Not found")

    def put(self, actor_id, relationship):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            add_response=False,
            config=self.config)
        if not myself:
            return
        if relationship != 'trustee':
            self.response.set_status(404, "Not found")
            return
        # Access is the same as /trust
        if not check.check_authorisation(path='trust', method='POST'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'trustee_root' in params:
                trustee_root = params['trustee_root']
            else:
                trustee_root = ''
            if 'creator' in params:
                creator = params['creator']
            else:
                creator = None
        except ValueError:
            self.response.set_status(400, 'No json content')
            return
        if len(trustee_root) > 0:
            myself.set_property('trustee_root', trustee_root)
        if creator:
            myself.modify(creator=creator)
        self.response.set_status(204, 'No content')

    def delete(self, actor_id, relationship):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            add_response=False,
            config=self.config)
        if not myself:
            return
        if relationship != 'trustee':
            self.response.set_status(404, "Not found")
            return
        # Access is the same as /trust
        if not check.check_authorisation(path='trust', method='DELETE'):
            self.response.set_status(403)
            return
        myself.delete_property('trustee_root')
        self.response.set_status(204, 'No content')

    def post(self, actor_id, relationship):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            add_response=False,
            config=self.config)
        if not myself:
            self.response.set_status(404)
            logging.debug("Got trust creation request for unknown Actor(" + str(id) + ")")
            return
        if not check.check_authorisation(path='trust', subpath='<type>', method='POST'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'baseuri' in params:
                baseuri = params['baseuri']
            else:
                baseuri = ''
            if 'id' in params:
                peerid = params['id']
            else:
                peerid = ''
            if 'type' in params:
                peer_type = params['type']
            else:
                peer_type = ''
            if 'secret' in params:
                secret = params['secret']
            else:
                secret = ''
            if 'desc' in params:
                desc = params['desc']
            else:
                desc = ''
            if 'verify' in params:
                verification_token = params['verify']
            else:
                verification_token = None
        except ValueError:
            self.response.set_status(400, 'No json content')
            return

        if len(baseuri) == 0 or len(peerid) == 0 or len(peer_type) == 0:
            self.response.set_status(400, 'Missing mandatory attributes')
            return
        if self.config.auto_accept_default_relationship and self.config.default_relationship == relationship:
            approved = True
        else:
            approved = False
        # Since we received a request for a relationship, assume that peer has approved
        new_trust = myself.create_verified_trust(
            baseuri=baseuri, peerid=peerid, approved=approved, secret=secret,
            verification_token=verification_token, trust_type=peer_type, peer_approved=True,
            relationship=relationship, desc=desc)
        if not new_trust:
            self.response.set_status(403, 'Forbidden')
            return
        self.response.headers["Location"] = str(self.config.root + myself.id +
                                                '/trust/' + new_trust["relationship"] +
                                                "/" + new_trust["peerid"])
        out = json.dumps(new_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        if approved:
            self.response.set_status(201, 'Created')
        else:
            self.response.set_status(202, 'Accepted')


# Handling requests to specific relationships, e.g. /trust/friend/12f2ae53bd
class TrustPeerHandler(base_handler.BaseHandler):

    def get(self, actor_id, relationship, peerid):
        if self.request.get('_method') == 'PUT':
            self.put(actor_id, relationship, peerid)
            return
        if self.request.get('_method') == 'DELETE':
            self.delete(actor_id, relationship, peerid)
            return
        logging.debug('GET trust headers: ' + str(self.request.headers))
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='trust', subpath='<type>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid)
        if not relationships or len(relationships) == 0:
            self.response.set_status(404, 'Not found')
            return
        my_trust = relationships[0]
        # If the peer did a GET to verify
        if check.trust and check.trust["peerid"] == peerid and not my_trust["verified"]:
            dbtrust = trust.Trust(actor_id=actor_id, peerid=peerid, config=self.config)
            dbtrust.modify(verified=True)
            # verification_token = my_trust["verification_token"]
        out = json.dumps(my_trust)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        if my_trust["approved"]:
            self.response.set_status(200, 'Ok')
        else:
            self.response.set_status(202, 'Accepted')

    def post(self, actor_id, relationship, peerid):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            peer_approved = None
            if 'approved' in params:
                if params['approved'] and params['approved'] is True:
                    peer_approved = True
        except ValueError:
            self.response.set_status(400, 'No json content')
            return
        if peer_approved:
            # If this is a notification from a peer about approval, we cannot check if the relationship is approved!
            if not check.check_authorisation(path='trust', subpath='<type>/<id>', method='POST', peerid=peerid,
                                             approved=False):
                self.response.set_status(403)
                return
        else:
            if not check.check_authorisation(path='trust', subpath='<type>/<id>', method='POST', peerid=peerid):
                self.response.set_status(403)
                return
        if myself.modify_trust_and_notify(relationship=relationship, peerid=peerid, peer_approved=peer_approved):
            self.response.set_status(204, 'Ok')
        else:
            self.response.set_status(405, 'Not modified')

    def put(self, actor_id, relationship, peerid):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='trust', subpath='<type>/<id>', method='PUT', peerid=peerid):
            self.response.set_status(403)
            return
        approved = None
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'baseuri' in params:
                baseuri = params['baseuri']
            else:
                baseuri = ''
            if 'desc' in params:
                desc = params['desc']
            else:
                desc = ''
            if 'approved' in params:
                if params['approved'] is True or params['approved'].lower() == "true":
                    approved = True
        except ValueError:
            if not self.request.get('_method') or self.request.get('_method') != "PUT":
                self.response.set_status(400, 'No json content')
                return
            if self.request.get('approved') and len(self.request.get('approved')) > 0:
                if self.request.get('approved').lower() == "true":
                    approved = True
            if self.request.get('baseuri') and len(self.request.get('baseuri')) > 0:
                baseuri = self.request.get('baseuri')
            else:
                baseuri = ''
            if self.request.get('desc') and len(self.request.get('desc')) > 0:
                desc = self.request.get('desc')
            else:
                desc = ''
        if myself.modify_trust_and_notify(relationship=relationship, peerid=peerid, baseuri=baseuri, approved=approved,
                                          desc=desc):
            self.response.set_status(204, 'Ok')
        else:
            self.response.set_status(405, 'Not modified')

    def delete(self, actor_id, relationship, peerid):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path='trust',
            subpath=relationship,
            add_response=False,
            config=self.config)
        if not myself or (check.response["code"] != 200 and check.response["code"] != 401):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        # We allow non-approved peers to delete even if we haven't approved the relationship yet
        if not check.check_authorisation(path='trust', subpath='<type>/<id>', method='DELETE', peerid=peerid,
                                         approved=False):
            self.response.set_status(403)
            return
        is_peer = False
        if check.trust and check.trust["peerid"] == peerid:
            is_peer = True
        else:
            # Use of GET param peer=true is a way of forcing no deletion of a peer
            # relationship even when requestor is not a peer (primarily for testing purposes)
            peer_get = self.request.get('peer').lower()
            if peer_get.lower() == "true":
                is_peer = True
        relationships = myself.get_trust_relationships(
            relationship=relationship, peerid=peerid)
        if not relationships or len(relationships) == 0:
            self.response.set_status(404, 'Not found')
            return
        if is_peer:
            deleted = myself.delete_reciprocal_trust(peerid=peerid, delete_peer=False)
        else:
            deleted = myself.delete_reciprocal_trust(peerid=peerid, delete_peer=True)
        if not deleted:
            self.response.set_status(502, 'Not able to delete relationship with peer.')
            return
        self.response.set_status(204, 'Ok')
