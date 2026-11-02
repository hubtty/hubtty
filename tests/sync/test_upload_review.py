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

"""Tests for UploadReviewTask and SendMergeTask."""

import datetime
import logging

import pytest
import requests
from unittest.mock import Mock, MagicMock, patch

from hubtty.db import Database
from hubtty.sync.exceptions import GraphQLError, OfflineError, RateLimitError
from hubtty.sync.tasks.pull_request import SyncPullRequestTask
from hubtty.sync.tasks.upload import (
    ENQUEUE_PULL_REQUEST_MUTATION,
    SendMergeTask,
    UploadReviewTask,
)


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


def _make_merge_env(merge_method, commit_title=None, commit_message=None,
                     node_id='NODE123'):
    """Build mock app, sync, session, and PendingMerge for SendMergeTask.

    Returns (mock_sync, mock_session, pending_merge, pull_request).
    """
    pr = Mock()
    pr.pr_id = PR_ID
    pr.node_id = node_id

    pending_merge = Mock()
    pending_merge.merge_method = merge_method
    pending_merge.sha = SHA
    pending_merge.commit_title = commit_title
    pending_merge.commit_message = commit_message
    pending_merge.pull_request = pr

    session = MagicMock()
    session.getPendingMerge = Mock(return_value=pending_merge)
    session.getPullRequestByPullRequestID = Mock(return_value=None)

    app = Mock()
    app.db.getSession.return_value.__enter__ = Mock(return_value=session)
    app.db.getSession.return_value.__exit__ = Mock(return_value=False)

    sync = Mock()
    sync.app = app
    sync.put = Mock()
    sync.graphql = Mock(return_value={})
    sync.submitTask = Mock()

    return sync, session, pending_merge, pr


def _run_merge(sync, pending_merge_key=1):
    """Run SendMergeTask with SyncPullRequestTask patched out."""
    task = SendMergeTask(pending_merge_key=pending_merge_key)
    with patch('hubtty.sync.tasks.pull_request.SyncPullRequestTask') as mock_cls:
        mock_cls.return_value.run = Mock()
        mock_cls.return_value.results = []
        task.run(sync)
    return task


class TestSendMergeTaskDirectMerge(object):
    """merge_method of 'merge'/'squash'/'rebase' uses the REST merge endpoint."""

    def test_puts_to_merge_endpoint(self):
        sync, session, pm, pr = _make_merge_env('squash')
        _run_merge(sync)

        sync.put.assert_called_once_with(
            f'repos/{PR_ID}/merge',
            {'sha': SHA, 'merge_method': 'squash'})
        sync.graphql.assert_not_called()
        session.delete.assert_called_once_with(pm)

    def test_includes_optional_commit_title_and_message(self):
        sync, session, pm, pr = _make_merge_env(
            'merge', commit_title='Title', commit_message='Message')
        _run_merge(sync)

        sync.put.assert_called_once_with(
            f'repos/{PR_ID}/merge',
            {'sha': SHA, 'merge_method': 'merge',
             'commit_title': 'Title', 'commit_message': 'Message'})

    def test_omits_blank_commit_title_and_message(self):
        sync, session, pm, pr = _make_merge_env('rebase')
        _run_merge(sync)

        sent_data = sync.put.call_args[0][1]
        assert 'commit_title' not in sent_data
        assert 'commit_message' not in sent_data

    def test_submits_followup_sync_pull_request_task(self):
        sync, session, pm, pr = _make_merge_env('merge')
        with patch('hubtty.sync.tasks.pull_request.SyncPullRequestTask') as mock_cls:
            mock_cls.return_value.run = Mock()
            mock_cls.return_value.results = []
            task = SendMergeTask(pending_merge_key=1)
            task.run(sync)
        sync.submitTask.assert_called_once()
        assert mock_cls.call_args[0][0] == PR_ID


class TestSendMergeTaskQueueMerge(object):
    """merge_method 'queue' uses the GraphQL enqueuePullRequest mutation."""

    def test_calls_graphql_enqueue_with_node_id(self):
        sync, session, pm, pr = _make_merge_env('queue', node_id='NODE123')
        _run_merge(sync)

        sync.graphql.assert_called_once_with(
            ENQUEUE_PULL_REQUEST_MUTATION, {'id': 'NODE123'})
        sync.put.assert_not_called()
        session.delete.assert_called_once_with(pm)
        sync.app.error.assert_not_called()

    def test_missing_node_id_syncs_then_enqueues(self):
        sync, session, pm, pr = _make_merge_env('queue', node_id=None)
        refreshed_pr = Mock()
        refreshed_pr.node_id = 'REFRESHED'
        session.getPullRequestByPullRequestID = Mock(return_value=refreshed_pr)

        _run_merge(sync)

        sync.graphql.assert_called_once_with(
            ENQUEUE_PULL_REQUEST_MUTATION, {'id': 'REFRESHED'})

    def test_still_missing_node_id_after_sync_raises(self):
        sync, session, pm, pr = _make_merge_env('queue', node_id=None)
        session.getPullRequestByPullRequestID = Mock(return_value=None)

        task = SendMergeTask(pending_merge_key=1)
        with patch('hubtty.sync.tasks.pull_request.SyncPullRequestTask') as mock_cls:
            mock_cls.return_value.run = Mock()
            mock_cls.return_value.results = []
            with pytest.raises(Exception, match='node id'):
                task.run(sync)
        sync.graphql.assert_not_called()


CLOSED_PR_REJECTION = (
    'Pull request is closed and Pull request 21 of 66 required status checks '
    'are expected.'
)
CHECKS_REJECTION = 'Pull request 21 of 66 required status checks are expected.'


def _enqueue_error(message=CLOSED_PR_REJECTION):
    return {'type': 'UNPROCESSABLE', 'path': ['enqueuePullRequest'],
            'locations': [{'line': 3, 'column': 3}], 'message': message}


class TestSendMergeTaskRejection:
    @pytest.mark.parametrize('reason', [CLOSED_PR_REJECTION, CHECKS_REJECTION])
    def test_reports_rejection_and_commits_deletion(self, reason, caplog):
        sync, session, pm, pr = _make_merge_env('queue')
        sync.graphql.side_effect = GraphQLError(
            'GraphQL error', errors=[_enqueue_error(reason)])

        with caplog.at_level(logging.WARNING, logger='hubtty.sync'):
            _run_merge(sync)

        session.delete.assert_called_once_with(pm)
        # Neither session exits with an exception that would roll back.
        exits = sync.app.db.getSession.return_value.__exit__.call_args_list
        assert len(exits) == 2
        assert all(call.args == (None, None, None) for call in exits)
        sync.app.error.assert_called_once()
        message = sync.app.error.call_args.args[0]
        assert PR_ID in message
        assert reason in message
        assert 'pending merge request was cleared' in message
        assert 'Submit a new merge request' in message
        sync.submitTask.assert_called_once()
        assert any(r.message == message and r.exc_info is None
                   for r in caplog.records)
        sync.put.assert_not_called()

    def test_combines_multiple_enqueue_validation_errors(self):
        sync, session, pm, pr = _make_merge_env('queue')
        sync.graphql.side_effect = GraphQLError(
            'GraphQL error', errors=[_enqueue_error('Pull request is closed'),
                                    _enqueue_error(CHECKS_REJECTION)])
        _run_merge(sync)
        message = sync.app.error.call_args.args[0]
        assert 'Pull request is closed' in message
        assert CHECKS_REJECTION in message

    @pytest.mark.parametrize('errors', [
        [],
        [{'message': 'unknown failure'}],
        [dict(_enqueue_error(), type='INTERNAL')],
        [dict(_enqueue_error(), path=['otherMutation'])],
        [_enqueue_error(), dict(_enqueue_error(), type='INTERNAL')],
        [_enqueue_error(), dict(_enqueue_error(), path=['otherMutation'])],
        [_enqueue_error(), None],
        [None],
        ['UNPROCESSABLE'],
        {'type': 'UNPROCESSABLE'},
        [dict(_enqueue_error(), path=None)],
        [dict(_enqueue_error(), path='enqueuePullRequest')],
        [dict(_enqueue_error(), message=None)],
        [dict(_enqueue_error(), message='')],
        [dict(_enqueue_error(), message='   ')],
    ])
    def test_unrecognized_mixed_or_malformed_errors_propagate(self, errors):
        sync, session, pm, pr = _make_merge_env('queue')
        error = GraphQLError('GraphQL error', errors=errors)
        sync.graphql.side_effect = error

        with pytest.raises(GraphQLError) as exc:
            _run_merge(sync)

        assert exc.value is error
        exit_args = sync.app.db.getSession.return_value.__exit__.call_args.args
        assert exit_args[0] is GraphQLError
        sync.app.error.assert_not_called()
        sync.submitTask.assert_not_called()

    @pytest.mark.parametrize('lookup', ['initial', 'before-api'])
    @pytest.mark.parametrize('method', ['queue', 'squash'])
    def test_missing_pending_action_is_noop(self, lookup, method):
        sync, session, pm, pr = _make_merge_env(method)
        session.getPendingMerge.side_effect = (
            [None] if lookup == 'initial' else [pm, None])
        _run_merge(sync)
        session.delete.assert_not_called()
        sync.graphql.assert_not_called()
        sync.put.assert_not_called()
        sync.app.error.assert_not_called()
        sync.submitTask.assert_not_called()


@pytest.fixture
def merge_database(mock_app, tmp_path):
    database = Database(mock_app, f'sqlite:///{tmp_path / "hubtty.db"}', None)
    try:
        with database.getSession() as session:
            repo = session.createRepository('owner/repo')
            author = session.createAccount(1, username='author')
            now = datetime.datetime.now(datetime.timezone.utc)
            pr = repo.createPullRequest(
                id=1, author=author, number=1, branch='main', pr_id=PR_ID,
                title='Test PR', body='', created=now, updated=now,
                state='open', additions=0, deletions=0,
                html_url='https://github.com/owner/repo/pull/1',
                merged=False, mergeable=True, node_id='NODE123')
            pm = pr.createPendingMerge(SHA, 'queue')
            key = pm.key
        yield database, key
    finally:
        database.session.remove()
        database.engine.dispose()


class TestSendMergeTaskTransactions:
    @pytest.mark.parametrize('reason', [CLOSED_PR_REJECTION, CHECKS_REJECTION])
    def test_rejection_removes_pending_action(self, mock_sync, merge_database,
                                              reason):
        database, key = merge_database
        mock_sync.app.db = database
        mock_sync.graphql.side_effect = GraphQLError(
            'GraphQL error', errors=[_enqueue_error(reason)])

        def check_committed(message):
            with database.getSession() as session:
                assert session.getPendingMerge(key) is None
            assert reason in message

        mock_sync.app.error.side_effect = check_committed
        SendMergeTask(key).run(mock_sync)

        with database.getSession() as session:
            assert session.getPendingMerges() == []
        mock_sync.app.error.assert_called_once()
        refresh = mock_sync.submitTask.call_args.args[0]
        assert isinstance(refresh, SyncPullRequestTask)
        assert refresh.pr_id == PR_ID

        # Re-uploading pending actions cannot resubmit the rejected request.
        mock_sync.submitTask.reset_mock()
        from hubtty.sync.tasks.upload import UploadReviewsTask
        UploadReviewsTask().run(mock_sync)
        mock_sync.submitTask.assert_not_called()

    @pytest.mark.parametrize('error', [
        requests.ConnectionError('disconnected'),
        requests.exceptions.ReadTimeout('timed out'),
        OfflineError('Received 503 status code'),
        RateLimitError('rate limited'),
        GraphQLError('non-JSON response'),
        GraphQLError('unknown failure', errors=[{'message': 'unknown failure'}]),
        GraphQLError('mixed errors', errors=[
            _enqueue_error(), dict(_enqueue_error(), type='INTERNAL')]),
        GraphQLError('malformed errors', errors=[None]),
    ])
    def test_failure_rolls_back_deletion(self, mock_sync, merge_database, error):
        database, key = merge_database
        mock_sync.app.db = database
        mock_sync.graphql.side_effect = error

        with pytest.raises(type(error)) as exc:
            SendMergeTask(key).run(mock_sync)

        assert exc.value is error
        with database.getSession() as session:
            assert session.getPendingMerge(key) is not None
        mock_sync.app.error.assert_not_called()
        mock_sync.submitTask.assert_not_called()

    def test_success_removes_pending_action(self, mock_sync, merge_database):
        database, key = merge_database
        mock_sync.app.db = database
        SendMergeTask(key).run(mock_sync)
        with database.getSession() as session:
            assert session.getPendingMerge(key) is None
        mock_sync.app.error.assert_not_called()
        mock_sync.submitTask.assert_called_once()
