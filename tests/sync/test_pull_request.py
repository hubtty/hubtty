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

"""Tests for pull request synchronization tasks."""

from unittest.mock import Mock, MagicMock, patch

from hubtty.sync.tasks.pull_request import SyncPullRequestTask
from hubtty.gitrepo import EMPTY_TREE_SHA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO = 'owner/repo'
PR_ID = f'{REPO}/pulls/1'
SHA_A = 'aaaa' * 10
SHA_B = 'bbbb' * 10


def _make_remote_pr():
    """Minimal GitHub PR API response."""
    return {
        'id': 1,
        'number': 1,
        'state': 'open',
        'title': 'Test PR',
        'body': 'desc',
        'created_at': '2025-01-01T00:00:00Z',
        'updated_at': '2025-01-02T00:00:00Z',
        'additions': 10,
        'deletions': 2,
        'html_url': f'https://github.com/{REPO}/pull/1',
        'merged': False,
        'mergeable': True,
        'draft': False,
        'labels': [],
        'user': {'id': 42, 'login': 'testuser'},
        'base': {
            'ref': 'main',
            'repo': {'full_name': REPO},
        },
    }


def _make_remote_commits(*shas):
    """Minimal GitHub PR commits API response."""
    commits = []
    parent = None
    for sha in shas:
        c = {
            'sha': sha,
            'commit': {'message': f'commit {sha[:8]}'},
            'parents': [{'sha': parent}] if parent else [],
        }
        commits.append(c)
        parent = sha
    return commits


def _make_commit_detail(sha, files=None):
    """Minimal GitHub commit detail API response."""
    if files is None:
        files = [{'filename': 'file.py', 'status': 'modified',
                  'additions': 5, 'deletions': 1, 'patch': '@@'}]
    return {'sha': sha, 'files': files}


def _setup_sync(mock_sync, remote_pr, remote_commits, commit_details,
                local_pr=None, local_commits_with_files=None):
    """Wire up mock_sync.get to return the right data for each URL.

    Args:
        mock_sync: The mock Sync object.
        remote_pr: PR detail response dict.
        remote_commits: Commits list response.
        commit_details: dict mapping SHA -> commit detail response.
        local_pr: Mock local PR (None = new PR).
        local_commits_with_files: set of SHAs that exist locally with
            files (used for the pre-fetch DB read).
    """
    app = mock_sync.app
    local_commits_with_files = local_commits_with_files or set()

    def get_side_effect(path, **kwargs):
        if path == f'repos/{PR_ID}':
            return remote_pr
        if path == f'repos/{PR_ID}/commits?per_page=100':
            return list(remote_commits)
        if path == f'repos/{PR_ID}/comments?per_page=50':
            return []
        if path == f'repos/{PR_ID}/reviews?per_page=100':
            return []
        if path == f'repos/{REPO}/issues/1/comments?per_page=100':
            return []
        # Commit detail
        for sha, detail in commit_details.items():
            if path == f'repos/{REPO}/commits/{sha}':
                return detail
        # Commit status / check-runs
        if '/status' in path:
            return {'statuses': []}
        if '/check-runs' in path:
            return []  # check runs (unwrapped by get())
        return {}

    mock_sync.get = Mock(side_effect=get_side_effect)

    # --- DB sessions ---
    # _syncPullRequest opens multiple DB sessions:
    #   1. Pre-fetch known commit SHAs (the new code)
    #   2. Main session for PR + commit + review processing
    #
    # Build a mock that returns the right objects for both.

    # Mock commit objects for the pre-fetch session
    pre_fetch_pr = None
    if local_commits_with_files:
        pre_fetch_commits = []
        for sha in local_commits_with_files:
            mc = Mock()
            mc.sha = sha
            mc.files = [Mock()]  # non-empty → has files
            pre_fetch_commits.append(mc)
        pre_fetch_pr = Mock()
        pre_fetch_pr.commits = pre_fetch_commits

    # Mock objects for the main session
    main_pr = local_pr
    if main_pr is None:
        # PR doesn't exist yet; session.getPullRequestByPullRequestID
        # returns None on first call (pre-fetch) and then the code
        # creates it via repository.createPullRequest.
        pass

    # Build session mocks
    pre_fetch_session = MagicMock()
    pre_fetch_session.getPullRequestByPullRequestID.return_value = pre_fetch_pr

    main_session = MagicMock()
    main_session.getPullRequestByPullRequestID.return_value = main_pr
    if main_pr is None:
        repo_mock = MagicMock()
        repo_mock.name = REPO
        repo_mock.key = 1
        created_pr = MagicMock()
        created_pr.repository = repo_mock
        created_pr.key = 100
        created_pr.pr_id = PR_ID
        created_pr.number = 1
        created_pr.state = 'open'
        created_pr.labels = []
        created_pr.commits = []
        repo_mock.createPullRequest.return_value = created_pr
        main_session.getRepositoryByName.return_value = repo_mock
        main_session.getPullRequestByPullRequestID.return_value = None
        main_pr = created_pr
    else:
        main_pr.labels = getattr(main_pr, 'labels', [])
        main_pr.commits = getattr(main_pr, 'commits', [])

    main_session.getAccountByID.return_value = Mock(key=42, username='testuser')

    # getSession is a context manager called multiple times.
    # Return pre_fetch_session first, then main_session for subsequent calls.
    sessions = iter([pre_fetch_session, main_session])
    ctx_managers = []
    for _ in range(2):
        cm = MagicMock()
        ctx_managers.append(cm)

    def make_ctx():
        cm = MagicMock()
        try:
            s = next(sessions)
        except StopIteration:
            s = main_session
        cm.__enter__ = Mock(return_value=s)
        cm.__exit__ = Mock(return_value=False)
        return cm

    app.db.getSession = make_ctx

    # Mock gitrepo.get_repo
    app.config.ignore_pending_checks = []
    app.repository_cache = MagicMock()

    return mock_sync


def _get_commit_detail_urls(mock_sync):
    """Extract commit-detail URLs from sync.get calls."""
    urls = []
    for c in mock_sync.get.call_args_list:
        path = c[0][0]
        # Commit detail URLs look like repos/{repo}/commits/{sha}
        # but NOT .../commits/{sha}/status or .../commits/{sha}/check-runs
        if '/commits/' in path and '/status' not in path \
                and '/check-runs' not in path \
                and '/pulls/' not in path:
            urls.append(path)
    return urls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSyncPullRequestCommitDetailSkip:
    """Verify that per-commit detail fetches are skipped for known commits."""

    @patch('hubtty.sync.tasks.pull_request.gitrepo')
    def test_skips_known_commits(self, mock_gitrepo, mock_sync):
        """Commits already in local DB with files are not re-fetched."""
        remote_pr = _make_remote_pr()
        remote_commits = _make_remote_commits(SHA_A, SHA_B)
        commit_details = {
            SHA_A: _make_commit_detail(SHA_A),
            SHA_B: _make_commit_detail(SHA_B),
        }

        _setup_sync(
            mock_sync, remote_pr, remote_commits, commit_details,
            local_commits_with_files={SHA_A, SHA_B},
        )

        task = SyncPullRequestTask(PR_ID)
        task.run(mock_sync)

        detail_urls = _get_commit_detail_urls(mock_sync)
        assert detail_urls == [], \
            f"Expected no commit-detail fetches, got: {detail_urls}"

    @patch('hubtty.sync.tasks.pull_request.gitrepo')
    def test_fetches_new_commits(self, mock_gitrepo, mock_sync):
        """Commits NOT in local DB are fetched normally."""
        remote_pr = _make_remote_pr()
        remote_commits = _make_remote_commits(SHA_A, SHA_B)
        commit_details = {
            SHA_A: _make_commit_detail(SHA_A),
            SHA_B: _make_commit_detail(SHA_B),
        }

        _setup_sync(
            mock_sync, remote_pr, remote_commits, commit_details,
            local_commits_with_files=set(),  # nothing known
        )

        task = SyncPullRequestTask(PR_ID)
        task.run(mock_sync)

        detail_urls = _get_commit_detail_urls(mock_sync)
        assert f'repos/{REPO}/commits/{SHA_A}' in detail_urls
        assert f'repos/{REPO}/commits/{SHA_B}' in detail_urls

    @patch('hubtty.sync.tasks.pull_request.gitrepo')
    def test_fetches_only_unknown_commits(self, mock_gitrepo, mock_sync):
        """Only new commits are fetched; known ones are skipped."""
        remote_pr = _make_remote_pr()
        remote_commits = _make_remote_commits(SHA_A, SHA_B)
        commit_details = {
            SHA_A: _make_commit_detail(SHA_A),
            SHA_B: _make_commit_detail(SHA_B),
        }

        # SHA_A is known, SHA_B is new
        _setup_sync(
            mock_sync, remote_pr, remote_commits, commit_details,
            local_commits_with_files={SHA_A},
        )

        task = SyncPullRequestTask(PR_ID)
        task.run(mock_sync)

        detail_urls = _get_commit_detail_urls(mock_sync)
        assert f'repos/{REPO}/commits/{SHA_A}' not in detail_urls, \
            "Known commit SHA_A should not be fetched"
        assert f'repos/{REPO}/commits/{SHA_B}' in detail_urls, \
            "New commit SHA_B should be fetched"


class TestSyncPullRequestParentlessCommit:
    """Verify that commits with no parents use the empty-tree SHA."""

    @patch('hubtty.sync.tasks.pull_request.gitrepo')
    def test_parentless_commit_uses_empty_tree_sha(
            self, mock_gitrepo, mock_sync):
        """A root commit (no parents) stores EMPTY_TREE_SHA as parent."""
        remote_pr = _make_remote_pr()
        # Build a single commit with an empty parents list.
        remote_commits = [{
            'sha': SHA_A,
            'commit': {'message': 'initial squashed import'},
            'parents': [],
        }]
        commit_details = {
            SHA_A: _make_commit_detail(SHA_A),
        }

        # Supply a local_pr mock so we can inspect createCommit calls
        # directly on it (no commits yet → getCommitBySha returns None).
        local_pr = MagicMock()
        local_pr.pr_id = PR_ID
        local_pr.number = 1
        local_pr.state = 'open'
        local_pr.labels = []
        local_pr.commits = []
        local_pr.repository = MagicMock(name=REPO)
        local_pr.repository.name = REPO
        local_pr.getCommitBySha = Mock(return_value=None)

        _setup_sync(
            mock_sync, remote_pr, remote_commits, commit_details,
            local_pr=local_pr,
        )

        mock_gitrepo.EMPTY_TREE_SHA = EMPTY_TREE_SHA
        task = SyncPullRequestTask(PR_ID)
        task.run(mock_sync)

        # createCommit must have been called with EMPTY_TREE_SHA as parent.
        local_pr.createCommit.assert_called_once_with(
            'initial squashed import',
            SHA_A,
            EMPTY_TREE_SHA,
        )
