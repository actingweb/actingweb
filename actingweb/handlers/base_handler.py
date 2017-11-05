from actingweb import aw_web_request, on_aw, config

class base_handler():

    def __init__(self,
                 webobj=aw_web_request.aw_webobj(),
                 config=config.config(),
                 on_aw=on_aw.on_aw_base()
                 ):
        self.request = webobj.request
        self.response = webobj.response
        self.config = config
        self.on_aw = on_aw

