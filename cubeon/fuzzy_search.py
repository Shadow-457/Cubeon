"""Bounded, cached fuzzy matching for local content names and identities."""
from functools import lru_cache
import re
import unicodedata

CONTENT_FIELDS = ('display_name', 'title', 'name', 'filename', 'mod_id', 'slug', 'project_id', 'stem')


@lru_cache(maxsize=4096)
def _forms(value):
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value[:192])
    value = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', value)
    value = ''.join(character for character in unicodedata.normalize('NFKD', value.casefold())
                    if not unicodedata.combining(character))
    words = tuple(re.findall(r'[^\W_]+', value))
    name_words = tuple(word for word in words if word not in ('jar', 'zip', 'disabled')
                       and not word.isdigit())
    return ' '.join(words), ''.join(words), words, ''.join(word[0] for word in name_words)


def _edit_distance(query, candidate, limit):
    if abs(len(query) - len(candidate)) > limit:
        return limit + 1
    previous = list(range(len(candidate) + 1))
    earlier = None
    for row, character in enumerate(query, 1):
        current = [row]
        for column, other in enumerate(candidate, 1):
            distance = min(current[-1] + 1, previous[column] + 1,
                           previous[column - 1] + (character != other))
            if (earlier is not None and column > 1 and character == candidate[column - 2]
                    and query[row - 2] == other):
                distance = min(distance, earlier[column - 2] + 1)
            current.append(distance)
        if min(current) > limit:
            return limit + 1
        earlier, previous = previous, current
    return previous[-1]


def _word_score(query, candidate):
    if query == candidate:
        return 1000
    if candidate.startswith(query):
        return 900
    if query in candidate:
        return 800
    if len(query) < 3 or len(candidate) < 3:
        return 0
    limit = min(3, max(1, len(query) // 4))
    distance = _edit_distance(query, candidate, limit)
    if distance <= limit:
        return 650 - distance * 40 - abs(len(query) - len(candidate)) * 5
    if (query[0] == candidate[0] and len(query) >= len(candidate) * .6
            and len(query) < len(candidate)):
        cursor = iter(candidate)
        if all(any(character == other for other in cursor) for character in query):
            return 450
    return 0


@lru_cache(maxsize=8192)
def _score(query, values):
    normalized, compact, query_words, _initials = _forms(query)
    if not query_words:
        return 0
    forms = [_forms(value) for value in values]
    best = 0
    for text, joined, words, initials in forms:
        if normalized == text or compact == joined:
            best = max(best, 1200)
        elif text.startswith(normalized) or joined.startswith(compact):
            best = max(best, 1100)
        elif normalized in text or compact in joined:
            best = max(best, 1000)
        elif len(compact) >= 3 and compact == initials:
            best = max(best, 950)
        if len(query_words) == 1:
            best = max(best, _word_score(compact, joined))
    candidates = tuple(dict.fromkeys(word for _text, _joined, words, _initials in forms for word in words))
    scores = [max((_word_score(word, candidate) for candidate in candidates), default=0)
              for word in query_words]
    if scores and all(scores):
        best = max(best, min(scores) + sum(scores) / len(scores) / 100)
    return best


def search_items(items, query, *, fields=CONTENT_FIELDS):
    """Rank exact/prefix matches before typo/abbreviation matches, without I/O."""
    query = str(query or '').strip()[:96]
    if not query:
        return list(items)
    matches = []
    for position, item in enumerate(items):
        values = tuple(str(item[field]) for field in fields if item.get(field))
        score = _score(query, values)
        if score:
            matches.append((score, position, item))
    matches.sort(key=lambda match: (-match[0], match[1]))
    return [item for _score_value, _position, item in matches]
