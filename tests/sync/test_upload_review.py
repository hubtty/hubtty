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

"""Tests for UploadReviewTask — empty-body guard against GitHub 422."""

from unittest.mock import Mock, MagicMock, patch

from hubtty.sync.tasks.upload import UploadReviewTask


PR_ID = 'owner/repo/pulls/1'
SHA = 'a' * 40


def _make_env(event, body, draft_comments=None):
    """Build mock app, sync, and DB objects for UploadReviewTask.

    Args:
        event: The approval event string (e.g. 'COMMENT', 'APPROVE').
        body: The review message body text.
        draft_comments: Optional list of (path, line, message, parent) tuples
            representing inline draft comments on the last commit's files.

    Returns:
        (mock_sync, mock_session) tuple.
    """
    # -- Approval --
    approval = Mock()
    approval.state = event

    # -- File(s) with optional draft comments --
    files = []
    if draft_comments:
        for path, line, msg, parent in draft_comments:
            comment = Mock()
            comment.line = line
            comment.message = msg
            comment.parent = parent
            f = Mock()
            f.path = path
            f.draft_comments = [comment]
            files.append(f)
    else:
        f = Mock()
        f.path = 'file.py'
        f.draft_comments = []
        files.append(f)

    # -- Commit (the only / last commit) --
    commit = Mock()
    commit.sha = SHA
    commit.files = files

    # -- Message --
    message = Mock()
    message.message = body
    message.commit = commit

    # -- Pull request --
    pr = Mock()
    pr.pr_id = PR_ID
    pr.held = False
    pr.draft_approvals = [approval]
    pr.commits = [commit]

    # Wire commit → PR
    commit.pull_request = pr

    # -- Session --
    session = MagicMock()
    session.getMessage = Mock(return_value=message)

    # -- App / DB --
    app = Mock()
    app.db.getSession.return_value.__enter__ = Mock(return_value=session)
    app.db.getSession.return_value.__exit__ = Mock(return_value=False)

    # -- Sync --
    sync = Mock()
    sync.app = app
    sync.post = Mock(return_value={})
    sync.submitTask = Mock()

    return sync, session


def _run(sync):
    """Run UploadReviewTask with SyncPullRequestTask patched out."""
    task = UploadReviewTask(message_key=1)
    # Patch SyncPullRequestTask so the held-check sync is a no-op
    with patch('hubtty.sync.tasks.pull_request.SyncPullRequestTask') as mock_cls:
        mock_cls.return_value.run = Mock()
        mock_cls.return_value.results = []
        task.run(sync)
    return task


class TestUploadReviewTaskEmptyBody:
    """Empty COMMENT / REQUEST_CHANGES reviews must not be POSTed."""

    def test_empty_comment_review_is_skipped(self):
        """COMMENT event + empty body + no inline comments → no POST."""
        sync, session = _make_env('COMMENT', '')
        _run(sync)

        sync.post.assert_not_called()
        # Approval and message should still be cleaned up locally
        deleted = [c.args[0] for c in session.delete.call_args_list]
        assert any(getattr(d, 'state', None) == 'COMMENT' for d in deleted)
        assert any(getattr(d, 'message', None) == '' for d in deleted)

    def test_empty_request_changes_review_is_skipped(self):
        """REQUEST_CHANGES event + empty body + no comments → no POST."""
        sync, _ = _make_env('REQUEST_CHANGES', '')
        _run(sync)

        sync.post.assert_not_called()

    def test_whitespace_only_comment_review_is_skipped(self):
        """COMMENT event + whitespace-only body + no comments → no POST."""
        sync, _ = _make_env('COMMENT', '   ')
        _run(sync)

        sync.post.assert_not_called()

    def test_nonempty_comment_review_is_posted(self):
        """COMMENT event + non-empty body → POST happens."""
        sync, _ = _make_env('COMMENT', 'Looks good')
        _run(sync)

        sync.post.assert_called_once()
        data = sync.post.call_args[0][1]
        assert data['body'] == 'Looks good'
        assert data['event'] == 'COMMENT'

    def test_empty_approve_review_is_posted(self):
        """APPROVE event + empty body → POST happens (body not required)."""
        sync, _ = _make_env('APPROVE', '')
        _run(sync)

        sync.post.assert_called_once()
        data = sync.post.call_args[0][1]
        assert data['event'] == 'APPROVE'

    def test_comment_with_inline_comments_is_posted(self):
        """COMMENT event + empty body + inline comments → POST happens."""
        sync, _ = _make_env(
            'COMMENT', '',
            draft_comments=[('file.py', 10, 'nit', False)],
        )
        _run(sync)

        sync.post.assert_called_once()
        data = sync.post.call_args[0][1]
        assert data['event'] == 'COMMENT'
        assert len(data['comments']) == 1
        assert data['comments'][0]['body'] == 'nit'

    def test_comment_with_parent_side_comment(self):
        """Inline comment with parent=True sends side=LEFT."""
        sync, _ = _make_env(
            'APPROVE', 'ok',
            draft_comments=[('old.py', 5, 'fix', True)],
        )
        _run(sync)

        sync.post.assert_called_once()
        data = sync.post.call_args[0][1]
        assert data['comments'][0]['side'] == 'LEFT'
