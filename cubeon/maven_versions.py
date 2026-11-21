# SPDX-License-Identifier: Apache-2.0
"""Maven ComparableVersion ordering for Forge/NeoForge version ranges.

Python adaptation of Apache Maven's ComparableVersion (3.8.8), modified for
Cubeon. Copyright The Apache Software Foundation. Licensed under the Apache
License, Version 2.0: https://www.apache.org/licenses/LICENSE-2.0
Source: https://github.com/apache/maven/blob/maven-3.8.8/maven-artifact/src/main/java/org/apache/maven/artifact/versioning/ComparableVersion.java
"""

_QUALIFIERS = ('alpha', 'beta', 'milestone', 'rc', 'snapshot', '', 'sp')
_ALIASES = {'ga': '', 'final': '', 'release': '', 'cr': 'rc'}


def _qualifier(value):
    return (_QUALIFIERS.index(value), '') if value in _QUALIFIERS else (7, value)


def _string(value, followed_by_digit=False):
    if followed_by_digit:
        value = {'a': 'alpha', 'b': 'beta', 'm': 'milestone'}.get(value, value)
    return _ALIASES.get(value, value)


def _items(version):
    version = str(version or '').strip().lower()
    root = current = []
    stack = [root]
    digit = False
    start = 0

    def descend():
        nonlocal current
        child = []
        current.append(child)
        current = child
        stack.append(child)

    def append(end):
        value = version[start:end]
        current.append(int(value) if digit and value else _string(value) if value else 0)

    for index, char in enumerate(version):
        if char in '.-':
            append(index)
            start = index + 1
            if char == '-':
                descend()
        elif char.isdecimal():
            if not digit and index > start:
                if current:
                    descend()
                current.append(_string(version[start:index], True))
                start = index
                descend()
            digit = True
        else:
            if digit and index > start:
                append(index)
                start = index
                descend()
            digit = False
    if len(version) > start:
        if not digit and current:
            descend()
        append(len(version))
    for group in reversed(stack):
        for index in range(len(group) - 1, -1, -1):
            value = group[index]
            if value in (0, '', []):
                del group[index]
            elif not isinstance(value, list):
                break
    return root


def _compare(left, right):
    if left is None:
        return 0 if right is None else -_compare(right, None)
    if isinstance(left, int):
        if right is None:
            return (left > 0) - (left < 0)
        return (left > right) - (left < right) if isinstance(right, int) else 1
    if isinstance(left, str):
        if right is None:
            right = ''
        if not isinstance(right, str):
            return -1
        a, b = _qualifier(left), _qualifier(right)
        return (a > b) - (a < b)
    if isinstance(right, int):
        return -1
    if isinstance(right, str):
        return 1
    right = [] if right is None else right
    for index in range(max(len(left), len(right))):
        result = _compare(left[index] if index < len(left) else None,
                          right[index] if index < len(right) else None)
        if result:
            return result
    return 0


def compare(left, right):
    return _compare(_items(left), _items(right))
