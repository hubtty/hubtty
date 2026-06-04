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

"""Tests for App.parseInternalURL with the new /owner/repo/pull/N format."""

import re
import types

from unittest.mock import Mock


# ---------------------------------------------------------------------------
# Helpers – build a minimal object that has parseInternalURL bound to it
# ---------------------------------------------------------------------------

def _make_parser(base_url='https://github.com/'):
    """Return a lightweight object with parseInternalURL and the
    attributes it relies on (config.url, trailing_filename_re)."""

    obj = Mock()
    obj.config.url = base_url
    obj.trailing_filename_re = re.compile(r'.*(,[a-z]+)')

    # Bind the real implementation from app.py source so we test the
    # actual logic, not a mock.
    from hubtty.app import App
    obj.parseInternalURL = types.MethodType(App.parseInternalURL, obj)
    return obj


# ---------------------------------------------------------------------------
# /owner/repo/pull/N  (path-based)
# ---------------------------------------------------------------------------

class TestPathBasedURLs:
    def test_valid_pr_url(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World/pull/123')
        assert result == ('123', None, None)

    def test_pr_url_with_trailing_slash(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World/pull/123/')
        assert result == ('123', None, None)

    def test_pr_url_with_extra_path_segments(self):
        """Extra segments after the PR number are ignored; the important
        thing is that path[2]=='pull' and path[3] is a digit."""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World/pull/7/files')
        assert result == ('7', None, None)

    def test_issue_url_returns_none(self):
        """Issues are not PRs — should return None so the browser opens."""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World/issues/42')
        assert result is None

    def test_repo_root_returns_none(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World')
        assert result is None

    def test_non_numeric_pr_returns_none(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat/Hello-World/pull/abc')
        assert result is None

    def test_short_path_returns_none(self):
        """Paths with fewer than 4 segments and no 'pull' keyword."""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/octocat')
        assert result is None


# ---------------------------------------------------------------------------
# External URLs
# ---------------------------------------------------------------------------

class TestExternalURLs:
    def test_different_host_returns_none(self):
        p = _make_parser()
        result = p.parseInternalURL('https://example.com/owner/repo/pull/1')
        assert result is None

    def test_completely_different_url(self):
        p = _make_parser()
        result = p.parseInternalURL('https://gitlab.com/foo/bar')
        assert result is None


# ---------------------------------------------------------------------------
# Fragment-based URLs  (the else branch)
# ---------------------------------------------------------------------------

class TestFragmentBasedURLs:
    def test_empty_fragment_returns_none(self):
        """The new guard: empty fragment should return None, not crash."""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/#')
        assert result is None

    def test_empty_fragment_with_slashes_returns_none(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/#///')
        assert result is None

    def test_fragment_with_pr_number(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/#42')
        assert result == ('42', None, None)

    def test_fragment_with_c_prefix(self):
        """Legacy fragment format: #c/pr/patchset"""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/#c/99/2')
        assert result == ('99', '2', None)

    def test_fragment_with_filename(self):
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/#c/99/2/src/main.py')
        assert result == ('99', '2', 'src/main.py')

    def test_bare_base_url_with_no_fragment(self):
        """Base URL with no path and no fragment → empty path, empty
        fragment → should return None (guard) or (None, None, None)."""
        p = _make_parser()
        result = p.parseInternalURL('https://github.com/')
        # Empty path AND empty fragment → the guard returns None
        assert result is None


# ---------------------------------------------------------------------------
# Custom base URL
# ---------------------------------------------------------------------------

class TestCustomBaseURL:
    def test_github_enterprise(self):
        p = _make_parser('https://git.corp.example.com/')
        result = p.parseInternalURL(
            'https://git.corp.example.com/team/project/pull/55')
        assert result == ('55', None, None)

    def test_github_enterprise_issue_returns_none(self):
        p = _make_parser('https://git.corp.example.com/')
        result = p.parseInternalURL(
            'https://git.corp.example.com/team/project/issues/55')
        assert result is None
