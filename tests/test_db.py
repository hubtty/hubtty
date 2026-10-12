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

"""Tests for db.py model methods."""

from unittest.mock import Mock, patch

from hubtty.db import Repository, PullRequest


class TestRepositoryAvailableMergeMethods:
    """Tests for Repository.availableMergeMethods()."""

    def test_all_methods_enabled(self):
        repo = Repository('owner/repo', allow_merge_commit=True,
                          allow_squash_merge=True, allow_rebase_merge=True)
        methods = repo.availableMergeMethods()
        assert [m[0] for m in methods] == ['merge', 'squash', 'rebase']

    def test_only_squash(self):
        repo = Repository('owner/repo', allow_merge_commit=False,
                          allow_squash_merge=True, allow_rebase_merge=False)
        methods = repo.availableMergeMethods()
        assert methods == [('squash', 'Squash and merge')]

    def test_only_rebase(self):
        repo = Repository('owner/repo', allow_merge_commit=False,
                          allow_squash_merge=False, allow_rebase_merge=True)
        methods = repo.availableMergeMethods()
        assert methods == [('rebase', 'Rebase and merge')]

    def test_none_enabled_returns_empty(self):
        repo = Repository('owner/repo', allow_merge_commit=False,
                          allow_squash_merge=False, allow_rebase_merge=False)
        with patch('hubtty.db.log') as mock_log:
            methods = repo.availableMergeMethods()
        assert methods == []
        mock_log.debug.assert_called_once()

    def test_defaults_all_enabled(self):
        """Default constructor enables merge, squash, and rebase."""
        repo = Repository('owner/repo')
        methods = repo.availableMergeMethods()
        assert len(methods) == 3


class TestPullRequestAvailableMergeMethods:
    """Tests for PullRequest.availableMergeMethods()."""

    def _make_pr(self, merge_queue_required=False, merge_queue_method=None,
                 repo_methods=None):
        """Create a mock that has PullRequest.availableMergeMethods bound."""
        repo = Mock()
        if repo_methods is None:
            repo_methods = [('merge', 'Create a merge commit'),
                            ('squash', 'Squash and merge')]
        repo.availableMergeMethods.return_value = repo_methods

        branch = Mock()
        branch.name = 'main'
        branch.merge_queue_required = merge_queue_required
        branch.merge_queue_method = merge_queue_method
        repo.branches = [branch]

        pr = Mock(spec=[])
        pr.repository = repo
        pr.branch = 'main'
        # Bind the real methods to our mock
        pr._target_branch = lambda: PullRequest._target_branch(pr)
        pr.availableMergeMethods = (
            lambda: PullRequest.availableMergeMethods(pr))
        return pr

    def test_no_queue_delegates_to_repo(self):
        pr = self._make_pr()
        methods = pr.availableMergeMethods()
        assert [m[0] for m in methods] == ['merge', 'squash']

    def test_queue_with_known_method(self):
        pr = self._make_pr(merge_queue_required=True,
                           merge_queue_method='squash')
        methods = pr.availableMergeMethods()
        assert methods == [('squash', 'Squash and merge')]

    def test_queue_with_unknown_method_uses_raw_label(self):
        pr = self._make_pr(merge_queue_required=True,
                           merge_queue_method='custom')
        methods = pr.availableMergeMethods()
        assert methods == [('custom', 'custom')]

    def test_queue_without_method_returns_empty(self):
        pr = self._make_pr(merge_queue_required=True,
                           merge_queue_method=None)
        methods = pr.availableMergeMethods()
        assert methods == []


class TestPullRequestCanEnqueue:
    """Tests for PullRequest.canEnqueue()."""

    def _make_pr(self, merge_queue_required=False, can_push=True):
        repo = Mock()
        repo.can_push = can_push

        branch = Mock()
        branch.name = 'main'
        branch.merge_queue_required = merge_queue_required
        repo.branches = [branch]

        pr = Mock(spec=[])
        pr.repository = repo
        pr.branch = 'main'
        pr._target_branch = lambda: PullRequest._target_branch(pr)
        pr.canEnqueue = lambda: PullRequest.canEnqueue(pr)
        return pr

    def test_can_enqueue_when_queue_required_and_can_push(self):
        pr = self._make_pr(merge_queue_required=True, can_push=True)
        assert pr.canEnqueue() is True

    def test_cannot_enqueue_when_no_queue(self):
        pr = self._make_pr(merge_queue_required=False, can_push=True)
        assert pr.canEnqueue() is False

    def test_cannot_enqueue_when_no_push_permission(self):
        pr = self._make_pr(merge_queue_required=True, can_push=False)
        assert pr.canEnqueue() is False

    def test_cannot_enqueue_when_no_queue_and_no_push(self):
        pr = self._make_pr(merge_queue_required=False, can_push=False)
        assert pr.canEnqueue() is False

    def test_cannot_enqueue_when_branch_not_found(self):
        """If the target branch isn't synced locally, canEnqueue is False."""
        repo = Mock()
        repo.can_push = True
        repo.branches = []  # no branches synced
        pr = Mock(spec=[])
        pr.repository = repo
        pr.branch = 'main'
        pr._target_branch = lambda: PullRequest._target_branch(pr)
        pr.canEnqueue = lambda: PullRequest.canEnqueue(pr)
        assert pr.canEnqueue() is False
