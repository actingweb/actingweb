from builtins import object


class AWRequest(object):

    def get_header(self, header=''):
        header = header.lower()
        for k, v in self.headers.items():
            if header == k.lower():
                return v
        return ''

    def get(self, var=''):
        var = var.lower()
        for k, v in self.params.items():
            if var == k.lower():
                return v
        return ''

    def arguments(self):
        ret = []
        for k, v in self.params.items():
            ret.append(k)
        return ret

    def __init__(self, url=None, params=None, body=None, headers=None, cookies=None):
        self.headers = headers
        self.params = params
        self.body = body
        self.url = url
        self.cookies = cookies


class AWResponse(object):

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
            self.body = body.encode('utf-8')
        else:
            self.body = body

    def set_cookie(self, name, value, max_age=1209600, path='/', secure=True):
        self.cookies.append({
            'name': name,
            'value': value,
            'max_age': max_age,
            'path': path,
            'secure': secure
        })

    def set_redirect(self, url):
        self.redirect = url

    def __init__(self):
        self.status_code = 200
        self.status_message = 'Ok'
        self.headers = {}
        self.body = ''
        self.redirect = None
        self.cookies = []
        self.template_values = {}


class AWWebObj(object):

    def __init__(self, url=None, params=None, body=None, headers=None, cookies=None):
        self.request = AWRequest(url=url, params=params, body=body, headers=headers, cookies=cookies)
        self.response = AWResponse()
