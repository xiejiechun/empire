"""Anonymous detail reads through the shared downloader; no task registration."""
from uuid import uuid4

from empire.features.themes.detail_model import parse_detail, source_id

URL = 'https://applhb.longhuvip.com/w1/api/index.php'
DOMAIN = 'longhuvip.com'


def request_options(theme_id):
    source_id(theme_id)
    return {'data': {'c': 'Theme', 'a': 'InfoGet', 'ID': theme_id,
                     'Version': '5.23.0.4', 'VerSion': '5.23.0.4',
                     'PhoneOS': '1', 'PhoneOSNew': '1', 'DeviceID': str(uuid4())}}


async def fetch_detail(http, theme_id, *, project_id, max_retries=1):
    source_id(theme_id)
    if not project_id:
        raise ValueError('题材详情请求必须声明项目')
    response = await http.request('POST', URL, allowed_domains=(DOMAIN,),
                                  max_redirects=0, project_id=project_id,
                                  policy=http.response_policy('generic'),
                                  max_retries=max_retries,
                                  strip_credentials=True,
                                  attempt_options=lambda: request_options(theme_id))
    try:
        return parse_detail(response.json(), theme_id)
    finally:
        response.close()
