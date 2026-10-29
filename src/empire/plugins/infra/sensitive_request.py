"""Credential-bearing requests retain diagnostics without response bodies or URLs."""
from urllib.parse import urlsplit

import httpx


class SensitiveRequestError(RuntimeError):
    def __init__(self, error):
        super().__init__(f'Sensitive request failed ({type(error).__name__})')
        self.diagnostic_recorded = getattr(error, 'diagnostic_recorded', False)
        self.retryable_transport = isinstance(error, (httpx.TransportError, TimeoutError))


def failure_fields(method, url, error, response, attempt):
    parsed = urlsplit(url)
    return dict(
        error=f'Sensitive request failed ({type(error).__name__})', raw_body=None,
        request_url=f'{parsed.scheme}://{parsed.hostname}/',
        status_code=getattr(error, 'status_code', None) if response is None else response.status_code,
        metadata={'method': method.upper(), 'attempt': attempt, 'sensitive_body_omitted': True},
    )
