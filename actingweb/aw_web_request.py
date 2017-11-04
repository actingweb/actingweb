class aw_request():

    def get_header(self, header=''):
        header = header.lower()
        for k,v in self.headers.iteritems():
            if header == k.lower():
                return v
        return ''

    def get(self, var=''):
        var = var.lower()
        for k,v in self.params.iteritems():
            if var == k.lower():
                return v
        return ''

    def arguments(self):
        ret = []
        for k,v in self.params.iteritems():
            ret.append(k)
        return ret

    def __init__(self, url=None, params=None, body=None, headers=None):
        self.headers = headers
        self.params = params
        self.body = body
        self.url = url


class aw_response():

    def set_status(self, code=200, message='Ok'):
        if not code or code < 100 or code > 599:
            return False
        if not message:
            message = ''
        self.status_code = code
        self.status_message = message

    def write(self, body=None, encode=False):
        if not body:
            return False
        if encode:
            self.body = out.encode('utf-8')
        else:
            self.body = body

    def __init__(self):
        self.status_code = 200
        self.status_message = 'Ok'
        self.headers = {}
        self.body = ''
        self.template_values = {}


class aw_webobj():

    def redirect(self, url):
        self.redirect = url

    def __init__(self, url=None, params=None, body=None, headers=None):
        self.request = aw_request(url=url, params=params, body=body, headers=headers)
        self.response = aw_response()
        self.redirect = None
