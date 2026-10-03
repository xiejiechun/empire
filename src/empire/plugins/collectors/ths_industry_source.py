"""Industry catalogue and one complete, code-sorted response per industry."""
import re
from html.parser import HTMLParser

from empire.contracts.industries import MEMBER_LIMIT, market, name

BASE = 'https://q.10jqka.com.cn/thshy/'


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children).strip()

    def find(self, tag=None, css=None):
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if ((tag is None or child.tag == tag)
                        and (css is None or css in child.attrs.get('class', '').split())):
                    result.append(child)
                result.extend(child.find(tag, css))
        return result


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack, self.count = [self.root], 0
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 50000 or len(self.stack) > 100:
            raise ValueError('行业网页结构超过解析边界')
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def one(nodes, label):
    if len(nodes) != 1:
        raise ValueError('行业响应缺少或重复' + label)
    return nodes[0]


def parse_catalog(source):
    if '</html>' not in source.lower():
        raise ValueError('行业目录响应不完整')
    root = Document(source).root
    group = one(root.find(css='cate_inner'), '完整目录')
    rows = []
    for anchor in group.find('a'):
        match = re.fullmatch(r'https?://q\.10jqka\.com\.cn/thshy/detail/code/([0-9]{6})/',
                             anchor.attrs.get('href', ''))
        if not match:
            raise ValueError('行业目录链接身份无效')
        rows.append({'code': match[1], 'name': name(anchor.text())})
    if not 1 <= len(rows) <= 500 or len({r['code'] for r in rows}) != len(rows):
        raise ValueError('行业目录为空、重复或超过上限')
    return sorted(rows, key=lambda r: r['code'])


def members_url(industry):
    return BASE + f'detail/code/{industry}/field/code/order/asc/page/1/size/{MEMBER_LIMIT}/ajax/1/'


def parse_members(source, industry):
    if 'upass.10jqka.com.cn/login' in source:
        raise ValueError('同花顺要求登录，当前匿名会话无法读取该页；未发布不完整行业集合')
    if '</tbody>' not in source.lower() or '</table>' not in source.lower():
        raise ValueError('行业成分响应为空、校验页或被截断')
    root = Document(source).root
    identity = one([n for n in root.find('input') if n.attrs.get('id') == 'requestQuery'], '行业身份')
    if identity.attrs.get('value') != 'code/' + industry:
        raise ValueError('行业响应身份与请求不一致')
    infos = root.find(css='page_info')
    if not infos:
        pager = one(root.find(css='m-pager'), '单页分页栏')
        if pager.text() or pager.find('a'):
            raise ValueError('行业单页分页栏无效')
        info = '1/1'
    else:
        info = one(infos, '页码').text()
    if info != '1/1':
        raise ValueError('行业完整响应仍有分页或页码无效，拒绝发布截断集合')
    body = one(one(root.find('table', 'm-table'), '成分表').find('tbody'), '表格正文')
    members = []
    previous_code = ''
    for index, row in enumerate(body.find('tr')):
        cells = row.find('td')
        if len(cells) != 14 or cells[0].text() != str(index + 1):
            raise ValueError('行业成分字段或连续序号无效')
        code, label = cells[1].text(), name(cells[2].text())
        market(code)
        for cell in cells[1:3]:
            anchor = one(cell.find('a'), '证券链接')
            if not re.fullmatch(r'https?://stockpage\.10jqka\.com\.cn/' + code + '/?',
                                anchor.attrs.get('href', '')):
                raise ValueError('行业证券链接与代码不一致')
        if code <= previous_code:
            raise ValueError('行业成分代码未严格升序或重复，拒绝发布不完整集合')
        previous_code = code
        members.append([code, label])
    if not 1 <= len(members) < MEMBER_LIMIT:
        raise ValueError('行业成分为空或达到请求上限，无法确认完整集合')
    return members
