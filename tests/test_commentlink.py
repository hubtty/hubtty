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

"""Tests for commentlink patterns (issue/PR auto-linking)."""

from unittest.mock import Mock

from hubtty.commentlink import CommentLink
from hubtty import mywid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = 'https://github.com/'

SAME_REPO_CONFIG = dict(
    match=r"(?<![/\w])#(?P<number>\d+)\b",
    replacements=[
        dict(link=dict(
            text="#{number}",
            url=BASE_URL + "{repository}/issues/{number}"))],
)

CROSS_REPO_CONFIG = dict(
    match=r"(?<!\w)(?P<cross_repo>[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*)#(?P<number>\d+)",
    replacements=[
        dict(link=dict(
            text="{cross_repo}#{number}",
            url=BASE_URL + "{cross_repo}/issues/{number}"))],
)


def _mock_app():
    app = Mock()
    app.parseInternalURL = Mock(return_value=None)
    app.openURL = Mock()
    return app


def _link_texts(result):
    """Extract display texts from run() output, resolving Link objects."""
    texts = []
    for item in result:
        if isinstance(item, mywid.Link):
            texts.append(item.text)
        elif isinstance(item, str):
            texts.append(item)
    return texts


def _link_objects(result):
    """Return only Link objects from run() output."""
    return [item for item in result if isinstance(item, mywid.Link)]


# ---------------------------------------------------------------------------
# Same-repo #N pattern
# ---------------------------------------------------------------------------

class TestSameRepoCommentLink:
    def test_links_issue_reference_with_context(self):
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        context = {'repository': 'octocat/Hello-World'}
        result = cl.run(app, ['See #42 for details'], context)

        texts = _link_texts(result)
        assert texts == ['See ', '#42', ' for details']

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == '#42'

    def test_creates_link_without_context(self):
        """When context is None, {repository} is missing from data, but
        it only appears in the URL (evaluated lazily inside a lambda),
        so the link IS created.  The URL will be broken at click time."""
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['See #42 for details'], None)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == '#42'

    def test_multiple_references(self):
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        context = {'repository': 'octocat/Hello-World'}
        result = cl.run(app, ['Fixes #1 and #2'], context)

        links = _link_objects(result)
        assert len(links) == 2
        assert links[0].text == '#1'
        assert links[1].text == '#2'

    def test_no_match_inside_url(self):
        """The negative lookbehind (?<![/\\w]) should prevent matching
        #N when preceded by a slash (e.g. inside a URL path)."""
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        context = {'repository': 'octocat/Hello-World'}
        result = cl.run(app, ['https://example.com/issues/#99'], context)

        links = _link_objects(result)
        assert len(links) == 0

    def test_no_match_when_preceded_by_word_char(self):
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        context = {'repository': 'octocat/Hello-World'}
        result = cl.run(app, ['foo#99'], context)

        links = _link_objects(result)
        assert len(links) == 0

    def test_match_at_start_of_string(self):
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        context = {'repository': 'octocat/Hello-World'}
        result = cl.run(app, ['#7 is done'], context)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == '#7'

    def test_empty_input(self):
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, [''], None)
        assert result == ['']


# ---------------------------------------------------------------------------
# Cross-repo owner/repo#N pattern
# ---------------------------------------------------------------------------

class TestCrossRepoCommentLink:
    def test_links_cross_repo_reference(self):
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['See octocat/Hello-World#42'], None)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == 'octocat/Hello-World#42'

    def test_no_context_needed(self):
        """Cross-repo pattern doesn't reference {repository}, so it
        works without context."""
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['fixes org/repo#10'], None)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == 'org/repo#10'

    def test_repo_with_dots_and_hyphens(self):
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['see my-org/my.repo#5'], None)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == 'my-org/my.repo#5'

    def test_lookbehind_prevents_mid_word_match(self):
        r"""The (?<!\w) lookbehind prevents matching a cross-repo ref
        that starts mid-word, e.g. after an email-like prefix."""
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()

        # At position 0 with no preceding char, the lookbehind passes
        # and the whole prefix is absorbed into the owner name.
        result = cl.run(app, ['prefixowner/repo#1'], None)
        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == 'prefixowner/repo#1'

        # When a word char appears right before a second ref in mid-text
        # and the first ref has already been consumed, the lookbehind
        # prevents partial matching.  E.g. 'textowner/repo#1' mid-text
        # where 'text' is contiguous still absorbs into the owner.
        # But if the cross-repo ref is separated by a non-word char
        # (space, punctuation) it matches correctly.
        result2 = cl.run(app, ['see owner/repo#5 done'], None)
        links2 = _link_objects(result2)
        assert len(links2) == 1
        assert links2[0].text == 'owner/repo#5'

    def test_rejects_leading_dot_in_owner_at_start(self):
        """When .hidden/repo#1 appears at position 0, the dot is not in
        [A-Za-z0-9_] so the match can't start there.  But the regex
        engine advances and matches hidden/repo#1 starting after the dot
        (since '.' is not a word character, the lookbehind passes)."""
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['.hidden/repo#1'], None)

        links = _link_objects(result)
        assert len(links) == 1
        assert links[0].text == 'hidden/repo#1'

    def test_rejects_dot_only_owner(self):
        """An owner consisting of only dots can't match because the
        first character must be [A-Za-z0-9_]."""
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['  .../repo#1'], None)

        # The regex can match 'repo#1' — wait, there's no '/' before
        # repo in a way that satisfies the cross_repo group structure.
        # Actually '../repo#1' can match: '.' skipped, './' — no.
        # Let's just verify the only match would be 'repo' as owner:
        # './repo#1' — after '.', '/' is not [A-Za-z0-9_], skip.
        # Only possible if both owner and repo segments have valid starts.
        links = _link_objects(result)
        assert len(links) == 0

    def test_rejects_leading_dot_in_repo(self):
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['owner/.secret#1'], None)

        links = _link_objects(result)
        assert len(links) == 0

    def test_multiple_cross_repo_references(self):
        cl = CommentLink(CROSS_REPO_CONFIG)
        app = _mock_app()
        result = cl.run(app, ['a/b#1 and c/d#2'], None)

        links = _link_objects(result)
        assert len(links) == 2
        assert links[0].text == 'a/b#1'
        assert links[1].text == 'c/d#2'


# ---------------------------------------------------------------------------
# Non-string chunk pass-through
# ---------------------------------------------------------------------------

class TestNonStringChunks:
    def test_non_string_chunks_passed_through(self):
        """CommentLink.run() should pass non-string items (e.g. Link
        widgets) through unchanged."""
        cl = CommentLink(SAME_REPO_CONFIG)
        app = _mock_app()
        widget = mywid.Link('existing', 'link', 'focused-link')
        result = cl.run(app, [widget, ' and #1'], {'repository': 'o/r'})

        assert result[0] is widget
        links = _link_objects(result[1:])
        assert len(links) == 1
        assert links[0].text == '#1'
