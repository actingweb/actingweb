from builtins import object
from actingweb import aw_web_request, on_aw as on_aw_class, config as config_class


class BaseHandler(object):

    def __init__(self,
                 webobj=aw_web_request.AWWebObj(),
                 config=config_class.Config(),
                 on_aw=on_aw_class.OnAWBase()
                 ):
        self.request = webobj.request
        self.response = webobj.response
        self.config = config
        self.on_aw = on_aw
