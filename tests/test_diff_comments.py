# Copyright The Hubtty Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Rendering tests for inline comment headers and borders."""

import datetime
from unittest.mock import Mock

import pytest

from hubtty import gitrepo
from hubtty.view.diff import _comment_header, build_comment_widget
from hubtty.view.side_diff import SideDiffComment
from hubtty.view.unified_diff import UnifiedDiffComment


@pytest.fixture
def app():
    app = Mock()
    app.config.commentlinks = []
    app.config.syntax_highlighting = True
    app.config.max_highlight_size = 512 * 1024
    app.time.side_effect = lambda dt: dt + datetime.timedelta(hours=2)
    return app


@pytest.mark.parametrize('is_own, prefix', [
    (False, 'pr-message'), (True, 'pr-message-own'),
])
def test_header_styles_and_local_time(app, is_own, prefix):
    created = datetime.datetime(2026, 7, 7, 12, 13)
    header = _comment_header(app, {
        'author': 'Alice', 'created': created, 'is_own': is_own,
    })
    assert header == [
        (prefix + '-name', 'Alice'),
        (prefix + '-header', ' (2026-07-07 14:13)'),
        ('comment', ': '),
    ]
    app.time.assert_called_once_with(created)


def test_header_without_timestamp(app):
    assert _comment_header(app, {'author': 'Alice'}) == [
        ('pr-message-name', 'Alice'), ('comment', ': '),
    ]
    app.time.assert_not_called()


@pytest.mark.parametrize('is_reply', [False, True])
@pytest.mark.parametrize('body', [
    'A long comment that wraps across several lines. ' * 4,
    'Introduction\n\n<details>\n<summary>Details</summary>\n\n'
    'A hidden explanation.\n\n</details>\n\nConclusion.',
])
def test_border_spans_every_rendered_row(app, is_reply, body):
    widget = build_comment_widget(app, {
        'author': 'Alice', 'body': body,
        'in_reply_to': 123 if is_reply else None,
    })
    canvas = widget.render((30,))
    assert canvas.rows() > 1
    for row in canvas.content():
        offset = 0
        borders = []
        for attr, _, text in row:
            if attr == 'comment-border':
                borders.append((offset, text))
            offset += len(text)
        assert borders == [(2 if is_reply else 0, b' ')]
    assert 'Alice:' in canvas.decoded_text[0]


@pytest.mark.parametrize('view', ['side', 'unified'])
def test_comment_renders_in_both_diff_layouts(app, view):
    comment = {'author': 'Alice', 'body': 'A wrapped comment. ' * 8}
    if view == 'side':
        widget = SideDiffComment(app, None, comment, comment)
    else:
        widget = UnifiedDiffComment(app, None, gitrepo.NEW, comment)
    canvas = widget.render((80,))
    assert canvas.cols() == 80
    assert canvas.rows() > 1
    assert 'Alice:' in canvas.decoded_text[0]


def test_draft_remains_unbordered(app):
    canvas = build_comment_widget(app, 'Draft comment').render((30,))
    assert canvas.decoded_text[0].strip() == 'Draft comment'
    assert all(attr != 'comment-border'
               for row in canvas.content() for attr, _, _ in row)
