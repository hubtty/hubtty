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

"""Tests for repository synchronization tasks."""

from unittest.mock import Mock, MagicMock

from hubtty.sync.http import SearchResult
from hubtty.sync.tasks.repository import (
    SyncRepositoryBranchesTask,
    SyncRepositoryListTask,
    SyncRepositoryTask,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pr(repo_name, number, state='open'):
    """Build a minimal search-result PR dict."""
    return {
        'pull_request': {
            'url': f'https://api.github.com/repos/{repo_name}/pulls/{number}',
        },
        'state': state,
    }


def _setup_sync(mock_sync, repositories):
    """Configure mock_sync and app with the given repositories.

    *repositories* is a list of (key, name, updated) tuples.
    Returns the list of repository keys.
    """
    repo_mocks = {}
    for key, name, updated in repositories:
        repo = Mock()
        repo.key = key
        repo.name = name
        repo.updated = updated
        repo_mocks[key] = repo

    session = MagicMock()
    session.getRepository = Mock(side_effect=lambda k: repo_mocks[k])
    session.getPullRequestIDs = Mock(return_value=set())

    mock_sync.app.db.getSession.return_value.__enter__ = Mock(
        return_value=session)
    mock_sync.app.db.getSession.return_value.__exit__ = Mock(
        return_value=False)

    return [key for key, _, _ in repositories]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSyncRepositoryTaskTruncation:
    """Tests for search-result truncation handling."""

    def test_no_truncation_uses_batch_results(self, mock_sync):
        """When total_count == len(items), no per-repo fallback occurs."""
        keys = _setup_sync(mock_sync, [
            (1, 'org/repo-a', None),
            (2, 'org/repo-b', None),
        ])

        prs = [_make_pr('org/repo-a', 1), _make_pr('org/repo-b', 2)]
        mock_sync.query = Mock(
            return_value=SearchResult(prs, len(prs)))

        task = SyncRepositoryTask(keys)
        task.run(mock_sync)

        # query() should have been called exactly once (the batch query).
        mock_sync.query.assert_called_once()
        q = mock_sync.query.call_args[0][0]
        assert 'repo:org/repo-a' in q
        assert 'repo:org/repo-b' in q

    def test_truncation_falls_back_to_per_repo(self, mock_sync):
        """When total_count > len(items), per-repo queries are issued."""
        keys = _setup_sync(mock_sync, [
            (1, 'org/repo-a', None),
            (2, 'org/repo-b', None),
        ])

        batch_prs = [_make_pr('org/repo-a', i) for i in range(5)]
        repo_a_prs = [_make_pr('org/repo-a', i) for i in range(3)]
        repo_b_prs = [_make_pr('org/repo-b', i) for i in range(4)]

        mock_sync.query = Mock(side_effect=[
            # First call: truncated batch result
            SearchResult(batch_prs, 1500),
            # Per-repo fallback calls
            SearchResult(repo_a_prs, len(repo_a_prs)),
            SearchResult(repo_b_prs, len(repo_b_prs)),
        ])

        task = SyncRepositoryTask(keys)
        task.run(mock_sync)

        assert mock_sync.query.call_count == 3
        # First call is the batch
        batch_q = mock_sync.query.call_args_list[0][0][0]
        assert 'repo:org/repo-a' in batch_q
        assert 'repo:org/repo-b' in batch_q
        # Second and third are per-repo
        repo_a_q = mock_sync.query.call_args_list[1][0][0]
        assert 'repo:org/repo-a' in repo_a_q
        assert 'repo:org/repo-b' not in repo_a_q
        repo_b_q = mock_sync.query.call_args_list[2][0][0]
        assert 'repo:org/repo-b' in repo_b_q
        assert 'repo:org/repo-a' not in repo_b_q

    def test_truncation_submits_tasks_from_fallback(self, mock_sync):
        """Per-repo fallback results are used to submit SyncPullRequestTasks."""
        keys = _setup_sync(mock_sync, [
            (1, 'org/repo-a', None),
        ])

        mock_sync.query = Mock(side_effect=[
            SearchResult([], 500),  # truncated batch
            SearchResult([_make_pr('org/repo-a', 1),
                          _make_pr('org/repo-a', 2)], 2),
        ])

        task = SyncRepositoryTask(keys)
        task.run(mock_sync)

        # Two open PRs -> two SyncPullRequestTask + one SetRepositoryUpdatedTask
        pr_task_calls = [
            c for c in mock_sync.submitTask.call_args_list
            if 'SyncPullRequestTask' in type(c[0][0]).__name__
        ]
        assert len(pr_task_calls) == 2

    def test_no_truncation_when_total_count_is_none(self, mock_sync):
        """When total_count is None, treat as not truncated."""
        keys = _setup_sync(mock_sync, [
            (1, 'org/repo-a', None),
        ])

        prs = [_make_pr('org/repo-a', 1)]
        mock_sync.query = Mock(return_value=SearchResult(prs, None))

        task = SyncRepositoryTask(keys)
        task.run(mock_sync)

        mock_sync.query.assert_called_once()


class TestSyncRepositoryListTaskMergeFlags:
    """Tests for the allow_*_merge null-coalescing in SyncRepositoryListTask."""

    def _run_with_remote_repo(self, mock_sync, remote_repo):
        """Run SyncRepositoryListTask with a single remote repo and return
        the repository object its attributes were written to."""
        repository = Mock()
        session = MagicMock()
        session.getRepositoryByName = Mock(return_value=repository)
        session.getRepositories = Mock(return_value=[])
        mock_sync.app.db.getSession.return_value.__enter__ = Mock(
            return_value=session)
        mock_sync.app.config.additional_repositories = []
        mock_sync.get = Mock(return_value=[remote_repo])

        task = SyncRepositoryListTask()
        task.run(mock_sync)
        return repository

    def test_null_bulk_merge_flags_coalesce_to_defaults(self, mock_sync):
        """GitHub's bulk listing returns these as null; defaults are used."""
        repository = self._run_with_remote_repo(mock_sync, {
            'full_name': 'org/repo',
            'description': '',
            'permissions': {'push': True},
            'allow_merge_commit': None,
            'allow_squash_merge': None,
            'allow_rebase_merge': None,
            'allow_auto_merge': None,
        })
        assert repository.allow_merge_commit is True
        assert repository.allow_squash_merge is True
        assert repository.allow_rebase_merge is True
        assert repository.allow_auto_merge is False

    def test_non_null_bulk_merge_flags_are_preserved(self, mock_sync):
        """Non-null values (even if inaccurate) are passed through as-is."""
        repository = self._run_with_remote_repo(mock_sync, {
            'full_name': 'org/repo',
            'description': '',
            'permissions': {'push': True},
            'allow_merge_commit': False,
            'allow_squash_merge': False,
            'allow_rebase_merge': False,
            'allow_auto_merge': True,
        })
        assert repository.allow_merge_commit is False
        assert repository.allow_squash_merge is False
        assert repository.allow_rebase_merge is False
        assert repository.allow_auto_merge is True


class TestSyncRepositoryBranchesTaskMergeSettings:
    """Tests for merge-settings sync folded into SyncRepositoryBranchesTask."""

    def _setup(self, mock_sync, remote_repo, remote_branches=None):
        """Configure mock_sync for a SyncRepositoryBranchesTask run.

        Returns the mock repository object whose attributes are set by
        the task.
        """
        if remote_branches is None:
            remote_branches = []

        repository = Mock()
        repository.branches = []
        repository.pull_requests = []
        session = MagicMock()
        session.getRepositoryByName = Mock(return_value=repository)
        mock_sync.app.db.getSession.return_value.__enter__ = Mock(
            return_value=session)

        # get() is called twice: once for the repo, once for branches.
        mock_sync.get = Mock(side_effect=[
            remote_repo,
            remote_branches,
        ])
        return repository

    def test_persists_real_values_from_single_repo_endpoint(self, mock_sync):
        repository = self._setup(mock_sync, {
            'allow_merge_commit': False,
            'allow_squash_merge': True,
            'allow_rebase_merge': False,
            'allow_auto_merge': True,
        })

        task = SyncRepositoryBranchesTask('org/repo')
        task.run(mock_sync)

        # First get() call should be the repo endpoint.
        assert mock_sync.get.call_args_list[0] == \
            (('repos/org/repo',), {'use_etag': True})
        assert repository.allow_merge_commit is False
        assert repository.allow_squash_merge is True
        assert repository.allow_rebase_merge is False
        assert repository.allow_auto_merge is True

    def test_missing_keys_use_defaults(self, mock_sync):
        # Non-empty (truthy) response, but missing the merge-flag keys.
        repository = self._setup(mock_sync, {'full_name': 'org/repo'})

        task = SyncRepositoryBranchesTask('org/repo')
        task.run(mock_sync)

        assert repository.allow_merge_commit is True
        assert repository.allow_squash_merge is True
        assert repository.allow_rebase_merge is True
        assert repository.allow_auto_merge is False

    def test_falsy_repo_response_skips_merge_settings(self, mock_sync):
        """A falsy repo response (304 Not Modified) skips merge-settings
        update but still processes branches."""
        repository = self._setup(
            mock_sync, None,
            remote_branches=[{'name': 'main'}],
        )

        task = SyncRepositoryBranchesTask('org/repo')
        task.run(mock_sync)

        # Merge-settings attributes should not have been set.
        # Mock.__setattr__ calls are tracked via the property mock;
        # verify none of the allow_* attrs were assigned.
        set_attrs = {name for name, _ in repository._mock_children.items()}
        for attr in ('allow_merge_commit', 'allow_squash_merge',
                     'allow_rebase_merge', 'allow_auto_merge'):
            assert attr not in set_attrs, \
                f'{attr} should not have been set on a falsy repo response'
        # Branch should still have been created.
        repository.createBranch.assert_called_once_with('main')
