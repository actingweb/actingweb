
from typing import Any

from actingweb import aw_web_request
from actingweb import config as config_class
from actingweb import on_aw as on_aw_class


class BaseHandler:

    def __init__(
        self,
        webobj: aw_web_request.AWWebObj = aw_web_request.AWWebObj(),
        config: config_class.Config = config_class.Config(),
        on_aw: on_aw_class.OnAWBase = on_aw_class.OnAWBase(),
    ) -> None:
        self.request = webobj.request
        self.response = webobj.response
        self.config = config
        self.on_aw = on_aw
