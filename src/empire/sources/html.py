"""Bounded HTML tree with browser-style optional table-cell closing."""
from html.parser import HTMLParser


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(''.join(c if isinstance(c, str) else c.text() for c in self.children).split())

    def find(self, tag=None, css=None):
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (css is None or css in child.attrs.get('class', '').split()):
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
            raise ValueError('持有人网页结构超限')
        if tag in ('td', 'th'):
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == 'table':
                    break
                if self.stack[i].tag == 'tr':
                    del self.stack[i + 1:]
                    break
        if tag == 'tr':
            # Optional row closing is scoped to the nearest table. A nested
            # detail table must never close its containing outer source row.
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == 'table':
                    break
                if self.stack[i].tag == 'tr':
                    del self.stack[i:]
                    break
        if tag in ('tbody', 'thead', 'tfoot'):
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == 'table':
                    break
                if self.stack[i].tag in ('tbody', 'thead', 'tfoot'):
                    del self.stack[i:]
                    break
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
