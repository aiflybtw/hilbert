from __future__ import annotations

import requests


class StealthSession:
    def __init__(self, user_agent: str | None = None, referer: str | None = None, cookies: dict | None = None):
        self.session = requests.Session()
        ua = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        self.session.headers.update(headers)
        if cookies:
            self.session.cookies.update(cookies)

    def get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=kwargs.pop("timeout", 15), **kwargs)
        resp.raise_for_status()
        return resp
