import urllib
import logging
import json

# This function code is from latest urlfetch. For some reason the
# Appengine version of urlfetch does not include links()


def PaginationLinks(self):
    """Links parsed from HTTP Link header"""
    ret = []
    if 'link' in self.headers:
        linkheader = self.headers['link']
    else:
        return ret
    for i in linkheader.split(','):
        try:
            url, params = i.split(';', 1)
        except ValueError:
            url, params = i, ''
        link = {}
        link['url'] = url.strip('''<> '"''')
        for param in params.split(';'):
            try:
                k, v = param.split('=')
            except ValueError:
                break
            link[k.strip(''' '"''')] = v.strip(''' '"''')
        ret.append(link)
    return ret


class oauth():

    def __init__(self, token=None, config=None):
        self.config = config.oauth
        self.token = token
        self.first = None
        self.next = None
        self.prev = None
        self.last_response_code = 0
        self.last_response_message = ""

    def enabled(self):
        if len(self.config['client_id']) == 0:
            return False
        else:
            return True

    def setToken(self, token):
        if token:
            self.token = token

    def postRequest(self, url, params=None, urlencode=False):
        if params:
            if urlencode:
                data = urllib.urlencode(params)
                logging.info('Oauth POST request with urlencoded payload: ' + url + ' ' + data)
            else:
                data = json.dumps(params)
                logging.info('Oauth POST request with JSON payload: ' + url + ' ' + data)
        else:
            data = None
            logging.info('Oauth POST request: ' + url)
        if urlencode:
            if self.token:
                headers = {'Content-Type': 'application/x-www-form-urlencoded',
                           'Authorization': 'Bearer ' + self.token,
                           }
            else:
                headers = {'Content-Type': 'application/x-www-form-urlencoded',
                           }
        else:
            if self.token:
                headers = {'Content-Type': 'application/json',
                           'Authorization': 'Bearer ' + self.token,
                           }
            else:
                headers = {'Content-Type': 'application/json'}
        try:
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"].fetch(
                    url=url,
                    payload=data,
                    method=self.config.module["urlfetch"].POST,
                    headers=headers)
            else:
                response = self.config.module["urlfetch"].post(url=url, data=data, headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except:
            self.last_response_code = 0
            self.last_response_message = 'No response'
            logging.warn("Oauth POST failed with exception")
            return None
        if response.status_code == 204:
            return {}
        if response.status_code != 200 and response.status_code != 201:
            logging.info('Error when sending POST request: ' +
                         str(response.status_code) + response.content)
            return None
        logging.debug('Oauth POST response JSON:' + response.content)
        return json.loads(response.content)

    def putRequest(self, url, params=None, urlencode=False):
        if params:
            if urlencode:
                data = urllib.urlencode(params)
                logging.info('Oauth PUT request with urlencoded payload: ' + url + ' ' + data)
            else:
                data = json.dumps(params)
                logging.info('Oauth PUT request with JSON payload: ' + url + ' ' + data)
        else:
            data = None
            logging.info('Oauth PUT request: ' + url)
        if urlencode:
            if self.token:
                headers = {'Content-Type': 'application/x-www-form-urlencoded',
                           'Authorization': 'Bearer ' + self.token,
                           }
            else:
                headers = {'Content-Type': 'application/x-www-form-urlencoded',
                           }
        else:
            if self.token:
                headers = {'Content-Type': 'application/json',
                           'Authorization': 'Bearer ' + self.token,
                           }
            else:
                headers = {'Content-Type': 'application/json'}
        try:
            if self.config.env == 'appengine':
                self.config.module["urlfetch"].set_default_fetch_deadline(20)
                response = self.config.module["urlfetch"](
                    url=url,
                    payload=data,
                    method=self.config.module["urlfetch"].PUT,
                    headers=headers)
            else:
                response = self.config.module["urlfetch"].post(url=url, data=data, headers=headers)
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except:
            self.last_response_code = 0
            self.last_response_message = 'No response'
            logging.warn("Oauth PUT failed with exception")
            return None
        if response.status_code == 204:
            return {}
        if response.status_code != 200 and response.status_code != 201:
            logging.info('Error when sending PUT request: ' +
                         str(response.status_code) + response.content)
            return None
        logging.debug('Oauth PUT response JSON:' + response.content)
        return json.loads(response.content)

    def getRequest(self, url, params=None):
        if not self.token:
            logging.debug("No token set in getRequest()")
            return None
        if params:
            url = url + '?' + urllib.urlencode(params)
        logging.info('Oauth GET request: ' + url)
        try:
            if self.config.env == 'appengine':
                urlfetch.self.config.module["urlfetch"].set_default_fetch_deadline(60)
                response = self.config.module["urlfetch"].fetch(
                    url=url,
                    method=self.config.module["urlfetch"].GET,
                    headers={
                        'Authorization': 'Bearer ' + self.token,
                    }
                    )
            else:
                response = self.config.module["urlfetch"].get(
                    url=url,
                    headers={
                        'Authorization': 'Bearer ' + self.token,
                    }
                    )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except:
            self.last_response_code = 0
            self.last_response_message = 'No response'
            logging.warn("Oauth GET failed with exception")
            return None
        if response.status_code < 200 or response.status_code > 299:
            logging.info('Error when sending GET request to Oauth: ' +
                         str(response.status_code) + response.content)
            return None
        links = PaginationLinks(response)
        self.next = None
        self.first = None
        self.prev = None
        for link in links:
            logging.debug('Links:' + link['rel'] + ':' + link['url'])
            if link['rel'] == 'next':
                self.next = link['url']
            elif link['rel'] == 'first':
                self.first = link['url']
            elif link['rel'] == 'prev':
                self.prev = link['url']
        return json.loads(response.content)

    def deleteRequest(self, url):
        if not self.token:
            return None
        logging.info('Oauth DELETE request: ' + url)
        try:
            if self.config.env == 'appengine':
                response = self.config.module["urlfetch"].fetch(url=url,
                                          method=self.config.module["urlfetch"].DELETE,
                                          headers={'Authorization': 'Bearer ' + self.token}
                                          )
            else:
                response = self.config.module["urlfetch"].delete(
                    url=url,
                    headers={'Authorization': 'Bearer ' + self.token}
                    )
            self.last_response_code = response.status_code
            self.last_response_message = response.content
        except:
            logging.warn("Spark DELETE failed.")
            self.last_response_code = 0
            self.last_response_message = 'No response'
            return None
        if response.status_code < 200 or response.status_code > 299:
            logging.info('Error when sending DELETE request to Oauth: ' +
                         str(response.status_code) + response.content)
            return None
        if response.status_code == 204:
            return {}
        try:
            ret = json.loads(response.content)
        except:
            return {}
        return ret

    def oauthRedirectURI(self, state=''):
        params = {
            'response_type': self.config['response_type'],
            'client_id': self.config['client_id'],
            'redirect_uri': self.config['redirect_uri'],
            'scope': self.config['scope'],
            'state': state,
        }
        uri = self.config['auth_uri'] + "?" + urllib.urlencode(params)
        logging.info('OAuth redirect with url: ' + uri + ' and state:' + state)
        return uri

    def oauthRequestToken(self, code=None):
        if not code:
            return None
        params = {
            'grant_type': self.config['grant_type'],
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'code': code,
            'redirect_uri': self.config['redirect_uri'],
        }
        self.token = None
        result = self.postRequest(url=self.config[
                                  'token_uri'], params=params, urlencode=True)
        if result and 'access_token' in result:
            self.token = result['access_token']
        return result

    def oauthRefreshToken(self, refresh_token):
        if not refresh_token:
            return None
        params = {
            'grant_type': self.config['refresh_type'],
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'refresh_token': refresh_token,
        }
        self.token = None
        result = self.postRequest(url=self.config[
                                  'token_uri'], params=params, urlencode=True)
        if not result:
            self.token = None
            return None
        self.token = result['access_token']
        return result
