from typing import Any


class AWRequest:
    def get_header(self, header: str = "") -> str:
        header = header.lower()
        if not self.headers:
            return ""
        for k, v in self.headers.items():
            if header == k.lower():
                return str(v)
        return ""

    def get(self, var: str = "") -> str:
        var = var.lower()
        if not self.params:
            return ""
        for k, v in self.params.items():
            if var == k.lower():
                return str(v)
        return ""

    def arguments(self) -> list[str]:
        ret: list[str] = []
        if not self.params:
            return ret
        for k, _v in self.params.items():
            ret.append(k)
        return ret

    def __init__(
        self,
        url: str | None = None,
        params: dict[str, Any] | None = None,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.headers = headers
        self.params = params
        self.body = body
        self.url = url
        self.cookies = cookies


class AWResponse:
    def set_status(self, code: int = 200, message: str = "Ok") -> bool | None:
        if not code or code < 100 or code > 599:
            return False
        if not message:
            message = ""
        self.status_code = code
        self.status_message = message
        return None

    def write(self, body: str | None = None, encode: bool = False) -> bool | None:
        if not body:
            return False
        if encode:
            self.body = body.encode("utf-8")
        else:
            self.body = body
        return None

    def set_cookie(
        self,
        name: str,
        value: str,
        max_age: int = 1209600,
        path: str = "/",
        secure: bool = True,
        httponly: bool = False,
        samesite: str = "Lax",
    ) -> None:
        self.cookies.append(
            {
                "name": name,
                "value": value,
                "max_age": max_age,
                "path": path,
                "secure": secure,
                "httponly": httponly,
                "samesite": samesite,
            }
        )

    def set_redirect(self, url: str) -> None:
        self.redirect = url

    def __init__(self) -> None:
        self.status_code = 200
        self.status_message = "Ok"
        self.headers: dict[str, str] = {}
        self.body: str | bytes = ""
        self.redirect: str | None = None
        self.cookies: list[dict[str, Any]] = []
        self.template_values: dict[str, Any] = {}


class AWWebObj:
    def __init__(
        self,
        url: str | None = None,
        params: dict[str, Any] | None = None,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.request = AWRequest(
            url=url, params=params, body=body, headers=headers, cookies=cookies
        )
        self.response = AWResponse()
