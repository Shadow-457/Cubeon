"""Generate homepage answer data from the questions and answers visitors read."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://www.ylet.online'


class Answers(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.answers = []
        self.question = self.answer = None
        self.mode = None
        self.hidden = 0
        self.answer_depth = 0
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button' and 'q-a' in attrs.get('class', '').split():
            self.question, self.answer = [], []
            self.mode = 'question'
        if tag == 'div' and 'q-body' in attrs.get('class', '').split():
            self.mode = 'answer'
            self.answer_depth = 1
        elif tag == 'div' and self.mode == 'answer':
            self.answer_depth += 1
        if tag == 'span' and self.mode == 'question' and attrs.get('aria-hidden') == 'true':
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag == 'span' and self.hidden:
            self.hidden -= 1
        if tag == 'button' and self.mode == 'question':
            self.mode = None
        if tag == 'p' and self.mode == 'answer':
            self.answer.append(' ')
        if tag == 'div' and self.mode == 'answer':
            self.answer_depth -= 1
        if tag == 'div' and self.mode == 'answer' and self.answer_depth == 0:
            self.answers.append({'@type': 'Question', 'name': self.clean(self.question),
                                 'acceptedAnswer': {'@type': 'Answer', 'text': self.clean(self.answer)}})
            self.mode = None

    def handle_data(self, data):
        if not self.hidden and self.mode:
            (self.question if self.mode == 'question' else self.answer).append(data)

    @staticmethod
    def clean(parts):
        return re.sub(r'\s+', ' ', ''.join(parts)).strip()


def update():
    path = ROOT / 'web/index.html'
    source = path.read_text()
    questions = Answers(source).answers
    if not questions or len({q['name'] for q in questions}) != len(questions):
        raise ValueError('Homepage needs unique, visible questions and answers')
    pattern = re.compile(r'(<script type="application/ld\+json">)\s*(.*?)\s*(</script>)', re.S)
    match = pattern.search(source)
    graph = json.loads(match.group(2))
    graph['@graph'] = [node for node in graph['@graph'] if node.get('@type') != 'FAQPage']
    graph['@graph'].append({'@type': 'FAQPage', '@id': ORIGIN + '/#faq', 'url': ORIGIN + '/#faq',
                            'name': 'Cubeon Launcher questions and answers',
                            'about': {'@id': ORIGIN + '/#launcher'},
                            'isPartOf': {'@id': ORIGIN + '/#webpage'}, 'mainEntity': questions})
    source = source[:match.start(2)] + json.dumps(graph, indent=2, ensure_ascii=False) + source[match.end(2):]
    path.write_text(source)
    print(f'Generated {len(questions)} FAQ answers from visible homepage text')


if __name__ == '__main__':
    update()
