import json

import httpx
import pytest

from empire.contracts.download import ResponsePolicy
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.sensitive_request import SensitiveRequestError


class Permits:
    async def eval(self, *args):
        return 0


class Records:
    def __init__(self):
        self.errors = []

    async def add_error(self, project_id, **values):
        self.errors.append(dict(project_id=project_id, **values))


@pytest.mark.parametrize('mode', ['http_error', 'transport', 'oversize', 'redirect'])
async def test_sensitive_failure_never_records_or_raises_credentials(mode):
    secret = 'credential_fixture_never_log'
    records = Records()

    def reply(request):
        if mode == 'transport':
            raise httpx.ReadError(secret)
        if mode == 'redirect':
            return httpx.Response(302, headers={'location': 'https://example.com/' + secret})
        return httpx.Response(200 if mode == 'oversize' else 403, content=secret.encode())

    http = HttpService(Permits(), 'sensitive_test', {}, records=records,
                       transport=httpx.MockTransport(reply))
    try:
        with pytest.raises(SensitiveRequestError) as caught:
            await http.request('POST', 'https://example.com/' + secret + '?session=' + secret,
                content=secret.encode(), allowed_domains=('example.com',), project_id='test-guest',
                max_redirects=0, max_retries=0, sensitive=True,
                policy=ResponsePolicy(10 if mode == 'oversize' else 100, 100))
        assert caught.value.diagnostic_recorded
        assert secret not in str(caught.value)
        assert len(records.errors) == 1
        assert secret not in json.dumps(records.errors)
        assert records.errors[0]['raw_body'] is None
        assert records.errors[0]['request_url'] == 'https://example.com/'
        assert records.errors[0]['metadata']['sensitive_body_omitted']
        assert http.buffer_budget.used == http.global_active == 0
    finally:
        await http.close()


async def test_success_keeps_sensitive_content_only_in_owned_response():
    records = Records()
    http = HttpService(Permits(), 'sensitive_test', {}, records=records,
                       transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'session-secret')))
    try:
        response = await http.request('GET', 'https://example.com/', allowed_domains=('example.com',),
                                      project_id='test-guest', max_redirects=0, sensitive=True)
        assert response.content == b'session-secret'
        response.close()
        assert response.content == b'' and not records.errors
        assert http.buffer_budget.used == 0
        with pytest.raises(ValueError, match='no-redirect'):
            await http.request('GET', 'https://example.com/', allowed_domains=('example.com',),
                               project_id='test-guest', sensitive=True)
    finally:
        await http.close()
