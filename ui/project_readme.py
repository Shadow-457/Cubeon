"""Render provider README HTML using the launcher's Markdown widget."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


def _safe_link(value):
    try:
        parsed = urlsplit(value or '')
        return value if parsed.scheme in ('https', 'http') and parsed.netloc else None
    except ValueError:
        return None


class _ReadmeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
        if self.hidden:
            return
        if tag == 'img':
            source = _safe_link(attributes.get('src'))
            if source:
                label = (attributes.get('alt') or '').replace('[', '').replace(']', '')
                self.parts.append(f'![{label}](<{source}>)')
        elif tag == 'a':
            link = _safe_link(attributes.get('href'))
            self.links.append(link)
            if link:
                self.parts.append('[')
        elif tag == 'br':
            self.parts.append('\n\n')
        elif tag in ('p', 'div', 'center', 'section', 'table', 'tr', 'ul', 'ol'):
            self.parts.append('\n\n')
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag in ('strong', 'b'):
            self.parts.append('**')
        elif tag in ('em', 'i'):
            self.parts.append('*')
        elif tag == 'code':
            self.parts.append('`')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag == 'a' and self.links:
            link = self.links.pop()
            if link:
                self.parts.append(f'](<{link}>)')
        elif tag in ('p', 'div', 'center', 'section', 'table', 'tr', 'ul', 'ol',
                     'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n\n')
        elif tag in ('strong', 'b'):
            self.parts.append('**')
        elif tag in ('em', 'i'):
            self.parts.append('*')
        elif tag == 'code':
            self.parts.append('`')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def readme_markdown(body):
    """Keep Markdown intact, translating embedded HTML without executing it."""
    source = (body or '').strip()
    if not re.search(r'</?(?:img|a|p|div|center|br|h[1-6]|strong|b|em|i|code|ul|ol|li|table|script|style)\b', source, re.I):
        return source
    parser = _ReadmeHTML()
    parser.feed(source)
    parser.close()
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()
