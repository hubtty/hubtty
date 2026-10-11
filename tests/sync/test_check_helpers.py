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

"""Tests for check_helpers module."""

from unittest.mock import Mock

import dateutil.parser
import pytest

from hubtty.sync.exceptions import OfflineError, RateLimitError
from hubtty.sync.tasks.check_helpers import (
    _fetch_classic_merge_queue_via_graphql,
    check_result_from_check_run,
    check_result_from_status,
    fetch_checks,
    fetch_merge_queue_rule,
    fetch_pending_workflow_approvals,
    has_pending_checks,
    update_checks,
)


class TestCheckResultFromCheckRun:
    """Tests for check_result_from_check_run."""

    def test_completed_success(self):
        """Completed check run with success conclusion."""
        remote = {
            'name': 'ci/test',
            'html_url': 'https://example.com/run/1',
            'status': 'completed',
            'conclusion': 'success',
            'started_at': '2024-01-01T10:00:00Z',
            'completed_at': '2024-01-01T10:05:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['name'] == 'ci/test'
        assert result['url'] == 'https://example.com/run/1'
        assert result['state'] == 'success'
        assert result['message'] == 'Job succeeded'
        assert result['started'] == '2024-01-01T10:00:00Z'
        assert result['finished'] == '2024-01-01T10:05:00Z'

    def test_completed_failure(self):
        """Completed check run with failure conclusion."""
        remote = {
            'name': 'ci/build',
            'html_url': 'https://example.com/run/2',
            'status': 'completed',
            'conclusion': 'failure',
            'started_at': '2024-01-01T10:00:00Z',
            'completed_at': '2024-01-01T10:03:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['state'] == 'failure'
        assert result['message'] == 'Job failed'

    def test_in_progress_is_pending(self):
        """In-progress check run maps to pending state."""
        remote = {
            'name': 'ci/lint',
            'status': 'in_progress',
            'started_at': '2024-01-01T10:00:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['state'] == 'pending'
        assert result['message'] == 'Job triggered'

    def test_queued_is_pending(self):
        """Queued check run maps to pending state."""
        remote = {
            'name': 'ci/deploy',
            'status': 'queued',
        }
        result = check_result_from_check_run(remote)
        assert result['state'] == 'pending'
        assert result['message'] == 'Job triggered'

    def test_missing_url_defaults_empty(self):
        """Missing html_url defaults to empty string."""
        remote = {
            'name': 'ci/test',
            'status': 'completed',
            'conclusion': 'success',
        }
        result = check_result_from_check_run(remote)
        assert result['url'] == ''

    def test_no_timestamps(self):
        """Check run without timestamps has no started/finished/created."""
        remote = {
            'name': 'ci/test',
            'status': 'queued',
        }
        result = check_result_from_check_run(remote)
        assert 'started' not in result
        assert 'finished' not in result
        assert 'created' not in result

    def test_started_sets_created_and_updated(self):
        """started_at populates created and updated fields."""
        remote = {
            'name': 'ci/test',
            'status': 'in_progress',
            'started_at': '2024-06-01T12:00:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['created'] == '2024-06-01T12:00:00Z'
        assert result['updated'] == '2024-06-01T12:00:00Z'

    def test_completed_skipped(self):
        """Completed check run with skipped conclusion."""
        remote = {
            'name': 'semver-label',
            'html_url': 'https://example.com/run/3',
            'status': 'completed',
            'conclusion': 'skipped',
            'started_at': '2024-01-01T10:00:00Z',
            'completed_at': '2024-01-01T10:00:01Z',
        }
        result = check_result_from_check_run(remote)
        assert result['state'] == 'skipped'
        assert result['message'] == 'Job skipped'
        assert 'started' not in result
        assert 'finished' not in result
        assert result['created'] == '2024-01-01T10:00:00Z'
        assert result['updated'] == '2024-01-01T10:00:01Z'

    def test_completed_cancelled(self):
        """Completed check run with cancelled conclusion."""
        remote = {
            'name': 'ci/deploy',
            'html_url': 'https://example.com/run/4',
            'status': 'completed',
            'conclusion': 'cancelled',
            'started_at': '2024-01-01T10:00:00Z',
            'completed_at': '2024-01-01T10:02:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['state'] == 'cancelled'
        assert result['message'] == 'Job cancelled'
        assert 'started' not in result
        assert 'finished' not in result
        assert result['created'] == '2024-01-01T10:00:00Z'
        assert result['updated'] == '2024-01-01T10:02:00Z'

    def test_completed_at_overrides_updated(self):
        """completed_at overrides updated field set by started_at."""
        remote = {
            'name': 'ci/test',
            'status': 'completed',
            'conclusion': 'success',
            'started_at': '2024-06-01T12:00:00Z',
            'completed_at': '2024-06-01T12:05:00Z',
        }
        result = check_result_from_check_run(remote)
        assert result['updated'] == '2024-06-01T12:05:00Z'
        assert result['created'] == '2024-06-01T12:00:00Z'


class TestCheckResultFromStatus:
    """Tests for check_result_from_status."""

    def test_success_status(self):
        """Successful commit status."""
        remote = {
            'context': 'ci/circleci',
            'target_url': 'https://circleci.com/build/1',
            'state': 'success',
            'description': 'All tests passed',
            'created_at': '2024-01-01T10:00:00Z',
            'updated_at': '2024-01-01T10:05:00Z',
        }
        result = check_result_from_status(remote)
        assert result['name'] == 'ci/circleci'
        assert result['url'] == 'https://circleci.com/build/1'
        assert result['state'] == 'success'
        assert result['message'] == 'All tests passed'
        assert result['created'] == '2024-01-01T10:00:00Z'
        assert result['updated'] == '2024-01-01T10:05:00Z'

    def test_pending_status(self):
        """Pending commit status."""
        remote = {
            'context': 'ci/jenkins',
            'state': 'pending',
            'description': 'Build queued',
            'created_at': '2024-01-01T10:00:00Z',
            'updated_at': '2024-01-01T10:00:00Z',
        }
        result = check_result_from_status(remote)
        assert result['state'] == 'pending'
        assert result['message'] == 'Build queued'

    def test_failure_status(self):
        """Failed commit status."""
        remote = {
            'context': 'ci/test',
            'state': 'failure',
            'description': '3 tests failed',
            'created_at': '2024-01-01T10:00:00Z',
            'updated_at': '2024-01-01T10:05:00Z',
        }
        result = check_result_from_status(remote)
        assert result['state'] == 'failure'

    def test_missing_url_defaults_empty(self):
        """Missing target_url defaults to empty string."""
        remote = {
            'context': 'ci/test',
            'state': 'success',
            'description': 'ok',
            'created_at': '2024-01-01T10:00:00Z',
            'updated_at': '2024-01-01T10:05:00Z',
        }
        result = check_result_from_status(remote)
        assert result['url'] == ''

    def test_missing_description_defaults_empty(self):
        """Missing description defaults to empty string."""
        remote = {
            'context': 'ci/test',
            'state': 'success',
            'created_at': '2024-01-01T10:00:00Z',
            'updated_at': '2024-01-01T10:05:00Z',
        }
        result = check_result_from_status(remote)
        assert result['message'] == ''


class TestHasPendingChecks:
    """Tests for has_pending_checks."""

    def test_empty_list(self):
        """Empty list has no pending checks."""
        assert has_pending_checks([]) is False

    def test_all_success(self):
        """All success means no pending."""
        checks = [
            {'state': 'success', 'name': 'a'},
            {'state': 'success', 'name': 'b'},
        ]
        assert has_pending_checks(checks) is False

    def test_one_pending(self):
        """One pending check is detected."""
        checks = [
            {'state': 'success', 'name': 'a'},
            {'state': 'pending', 'name': 'b'},
        ]
        assert has_pending_checks(checks) is True

    def test_all_pending(self):
        """All pending returns True."""
        checks = [
            {'state': 'pending', 'name': 'a'},
            {'state': 'pending', 'name': 'b'},
        ]
        assert has_pending_checks(checks) is True

    def test_mixed_states_no_pending(self):
        """Mix of success/failure but no pending."""
        checks = [
            {'state': 'success', 'name': 'a'},
            {'state': 'failure', 'name': 'b'},
        ]
        assert has_pending_checks(checks) is False

    def test_ignored_pending_not_counted(self):
        """A pending check in the ignore set is not counted."""
        checks = [
            {'state': 'success', 'name': 'ci/build'},
            {'state': 'pending', 'name': 'tide'},
        ]
        assert has_pending_checks(checks, frozenset(['tide'])) is False

    def test_ignored_plus_real_pending(self):
        """Ignored pending + non-ignored pending returns True."""
        checks = [
            {'state': 'pending', 'name': 'tide'},
            {'state': 'pending', 'name': 'ci/build'},
        ]
        assert has_pending_checks(checks, frozenset(['tide'])) is True

    def test_ignored_name_not_in_list(self):
        """Pending check not in ignore set is still counted."""
        checks = [
            {'state': 'pending', 'name': 'ci/build'},
        ]
        assert has_pending_checks(checks, frozenset(['tide'])) is True

    def test_empty_ignore_set_default_behavior(self):
        """Default empty frozenset preserves original behavior."""
        checks = [
            {'state': 'pending', 'name': 'tide'},
        ]
        assert has_pending_checks(checks) is True


class TestFetchChecks:
    """Tests for fetch_checks."""

    def test_fetches_statuses_and_check_runs(self):
        """Fetches both commit statuses and check runs."""
        sync = Mock()
        sync.get.side_effect = [
            # commit status response
            {'statuses': [
                {'context': 'ci/status', 'target_url': 'http://x',
                 'state': 'success', 'description': 'ok',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
            ]},
            # check runs response (unwrapped by get())
            [
                {'name': 'ci/check', 'html_url': 'http://y',
                 'status': 'completed', 'conclusion': 'failure',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:03:00Z'},
            ],
            # pending workflow-run approvals response (none)
            {'total_count': 0, 'workflow_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert len(result) == 2
        assert result[0]['name'] == 'ci/status'
        assert result[0]['state'] == 'success'
        assert result[1]['name'] == 'ci/check'
        assert result[1]['state'] == 'failure'

        # Verify API calls
        assert sync.get.call_count == 3
        sync.get.assert_any_call(
            'repos/owner/repo/commits/abc123/status', use_etag=True)
        sync.get.assert_any_call(
            'repos/owner/repo/commits/abc123/check-runs?per_page=100',
            use_etag=True)
        sync.get.assert_any_call(
            'repos/owner/repo/actions/runs?head_sha=abc123&per_page=100',
            use_etag=True)

    def test_empty_statuses_and_check_runs(self):
        """Returns empty list when no checks exist."""
        sync = Mock()
        sync.get.side_effect = [
            {'statuses': []},
            [],  # check runs (unwrapped by get())
            {'total_count': 0, 'workflow_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert result == []

    def test_only_statuses(self):
        """Returns only statuses when no check runs."""
        sync = Mock()
        sync.get.side_effect = [
            {'statuses': [
                {'context': 'ci/only', 'state': 'pending',
                 'description': 'waiting',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:00:00Z'},
            ]},
            [],  # check runs (unwrapped by get())
            {'total_count': 0, 'workflow_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert len(result) == 1
        assert result[0]['name'] == 'ci/only'

    def test_duplicate_name_check_run_wins(self):
        """When both APIs report the same name, check-run overwrites status."""
        sync = Mock()
        sync.get.side_effect = [
            {'statuses': [
                {'context': 'ci/build', 'target_url': 'http://old',
                 'state': 'pending', 'description': 'Waiting for status',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:00:00Z'},
            ]},
            [
                {'name': 'ci/build', 'html_url': 'http://new',
                 'status': 'completed', 'conclusion': 'success',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:05:00Z'},
            ],
            {'total_count': 0, 'workflow_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert len(result) == 1
        assert result[0]['name'] == 'ci/build'
        assert result[0]['state'] == 'success'
        assert result[0]['url'] == 'http://new'

    def test_multiple_duplicates_deduplicated(self):
        """Several overlapping names are all deduplicated."""
        sync = Mock()
        sync.get.side_effect = [
            {'statuses': [
                {'context': 'ci/a', 'state': 'success', 'description': 'ok',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
                {'context': 'ci/b', 'state': 'pending', 'description': 'wait',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:00:00Z'},
                {'context': 'ci/only-status', 'state': 'success',
                 'description': 'ok',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
            ]},
            [
                {'name': 'ci/a', 'html_url': 'http://a',
                 'status': 'completed', 'conclusion': 'failure',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:03:00Z'},
                {'name': 'ci/b', 'html_url': 'http://b',
                 'status': 'completed', 'conclusion': 'success',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:04:00Z'},
                {'name': 'ci/only-check', 'html_url': 'http://c',
                 'status': 'completed', 'conclusion': 'success',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:02:00Z'},
            ],
            {'total_count': 0, 'workflow_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        names = [c['name'] for c in result]
        assert sorted(names) == ['ci/a', 'ci/b', 'ci/only-check',
                                  'ci/only-status']
        # check-run values should win for the overlapping names
        by_name = {c['name']: c for c in result}
        assert by_name['ci/a']['state'] == 'failure'
        assert by_name['ci/b']['state'] == 'success'
        assert by_name['ci/b']['url'] == 'http://b'


class TestUpdateChecks:
    """Tests for update_checks."""

    def _make_check(self, name, state='success'):
        """Create a mock check object."""
        check = Mock()
        check.name = name
        check.key = f'key-{name}'
        check.state = state
        return check

    def _make_commit(self, checks):
        """Create a mock commit with checks."""
        commit = Mock()
        commit.checks = list(checks)
        commit.key = 'commit-1'
        return commit

    def test_creates_new_check(self):
        """New check is created when not in local DB."""
        session = Mock()
        commit = self._make_commit([])
        new_check = Mock()
        commit.createCheck.return_value = new_check

        checks_data = [{
            'name': 'ci/new',
            'state': 'success',
            'url': 'http://x',
            'message': 'Job succeeded',
            'created': '2024-01-01T10:00:00Z',
            'updated': '2024-01-01T10:05:00Z',
        }]
        update_checks(session, commit, checks_data)

        commit.createCheck.assert_called_once_with(
            'ci/new', 'success',
            dateutil.parser.parse('2024-01-01T10:00:00Z'),
            dateutil.parser.parse('2024-01-01T10:00:00Z'),
            run_id=None,
        )
        assert new_check.state == 'success'
        assert new_check.url == 'http://x'
        assert new_check.message == 'Job succeeded'
        assert new_check.run_id is None

    def test_updates_existing_check(self):
        """Existing check is updated with new state."""
        session = Mock()
        existing = self._make_check('ci/test', 'pending')
        commit = self._make_commit([existing])

        checks_data = [{
            'name': 'ci/test',
            'state': 'success',
            'url': 'http://x',
            'message': 'Job succeeded',
            'created': '2024-01-01T10:00:00Z',
            'updated': '2024-01-01T10:05:00Z',
        }]
        update_checks(session, commit, checks_data)

        assert existing.state == 'success'
        assert existing.url == 'http://x'
        assert existing.message == 'Job succeeded'
        commit.createCheck.assert_not_called()

    def test_deletes_removed_check(self):
        """Check not in remote data is deleted."""
        session = Mock()
        old_check = self._make_check('ci/old')
        commit = self._make_commit([old_check])

        checks_data = [{
            'name': 'ci/new',
            'state': 'success',
            'url': '',
            'message': 'ok',
            'created': '2024-01-01T10:00:00Z',
            'updated': '2024-01-01T10:05:00Z',
        }]
        commit.createCheck.return_value = Mock()
        update_checks(session, commit, checks_data)

        session.delete.assert_called_once_with(old_check)

    def test_sets_started_and_finished(self):
        """started and finished timestamps are set when present."""
        session = Mock()
        commit = self._make_commit([])
        new_check = Mock()
        commit.createCheck.return_value = new_check

        checks_data = [{
            'name': 'ci/test',
            'state': 'success',
            'url': '',
            'message': 'ok',
            'created': '2024-01-01T10:00:00Z',
            'updated': '2024-01-01T10:05:00Z',
            'started': '2024-01-01T10:00:00Z',
            'finished': '2024-01-01T10:05:00Z',
        }]
        update_checks(session, commit, checks_data)

        assert new_check.started == dateutil.parser.parse('2024-01-01T10:00:00Z')
        assert new_check.finished == dateutil.parser.parse('2024-01-01T10:05:00Z')

    def test_no_started_or_finished(self):
        """started/finished not set when absent from data."""
        session = Mock()
        existing = self._make_check('ci/test', 'pending')
        # Reset started/finished so we can verify they're not touched
        existing.started = None
        existing.finished = None
        commit = self._make_commit([existing])

        checks_data = [{
            'name': 'ci/test',
            'state': 'pending',
            'url': '',
            'message': 'Job triggered',
            'created': '2024-01-01T10:00:00Z',
            'updated': '2024-01-01T10:00:00Z',
        }]
        update_checks(session, commit, checks_data)

        assert existing.started is None
        assert existing.finished is None

    def test_multiple_checks(self):
        """Multiple checks are handled correctly."""
        session = Mock()
        existing = self._make_check('ci/keep', 'pending')
        stale = self._make_check('ci/stale')
        commit = self._make_commit([existing, stale])
        new_check = Mock()
        commit.createCheck.return_value = new_check

        checks_data = [
            {'name': 'ci/keep', 'state': 'success', 'url': '', 'message': 'ok',
             'created': '2024-01-01T10:00:00Z', 'updated': '2024-01-01T10:05:00Z'},
            {'name': 'ci/brand-new', 'state': 'pending', 'url': '', 'message': 'triggered',
             'created': '2024-01-01T10:00:00Z', 'updated': '2024-01-01T10:00:00Z'},
        ]
        update_checks(session, commit, checks_data)

        # ci/stale should be deleted
        session.delete.assert_called_once_with(stale)
        # ci/keep should be updated
        assert existing.state == 'success'
        # ci/brand-new should be created
        commit.createCheck.assert_called_once()

    def test_duplicate_names_in_input_creates_only_one(self):
        """Duplicate names in remote data must not create duplicate DB rows."""
        session = Mock()
        commit = self._make_commit([])
        created_check = Mock()
        commit.createCheck.return_value = created_check

        # Two entries with the same name (simulates pre-dedup data)
        checks_data = [
            {'name': 'ci/dup', 'state': 'pending', 'url': 'http://old',
             'message': 'Job triggered',
             'created': '2024-01-01T10:00:00Z',
             'updated': '2024-01-01T10:00:00Z'},
            {'name': 'ci/dup', 'state': 'success', 'url': 'http://new',
             'message': 'Job succeeded',
             'created': '2024-01-01T10:00:00Z',
             'updated': '2024-01-01T10:05:00Z'},
        ]
        update_checks(session, commit, checks_data)

        # Only one check should be created; second entry updates it
        commit.createCheck.assert_called_once()
        assert created_check.state == 'success'
        assert created_check.url == 'http://new'



class TestFetchPendingWorkflowApprovals:
    """Tests for fetch_pending_workflow_approvals."""

    def test_no_runs(self):
        """No workflow runs at all for this commit."""
        sync = Mock()
        sync.get.return_value = {'total_count': 0, 'workflow_runs': []}
        result = fetch_pending_workflow_approvals(sync, 'owner/repo', 'abc123')
        assert result == []
        sync.get.assert_called_once_with(
            'repos/owner/repo/actions/runs?head_sha=abc123&per_page=100',
            use_etag=True,
        )

    def test_ignores_non_action_required_runs(self):
        """Runs that aren't awaiting approval are not surfaced."""
        sync = Mock()
        sync.get.return_value = {
            'total_count': 2,
            'workflow_runs': [
                {'id': 1, 'name': 'CI', 'html_url': 'http://x/1',
                 'status': 'completed', 'conclusion': 'success',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
                {'id': 2, 'name': 'Lint', 'html_url': 'http://x/2',
                 'status': 'in_progress', 'conclusion': None,
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
            ],
        }
        result = fetch_pending_workflow_approvals(sync, 'owner/repo', 'abc123')
        assert result == []

    def test_surfaces_action_required_status_runs(self):
        """Runs with status == 'action_required' are surfaced."""
        sync = Mock()
        sync.get.return_value = {
            'total_count': 1,
            'workflow_runs': [
                {'id': 42, 'name': 'CI', 'html_url': 'http://x/42',
                 'status': 'action_required', 'conclusion': None,
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
            ],
        }
        result = fetch_pending_workflow_approvals(sync, 'owner/repo', 'abc123')
        assert len(result) == 1
        assert result[0]['name'] == 'workflow-approval: CI'
        assert result[0]['state'] == 'action_required'
        assert result[0]['run_id'] == 42
        assert result[0]['url'] == 'http://x/42'

    def test_surfaces_action_required_conclusion_runs(self):
        """Runs with conclusion == 'action_required' are surfaced."""
        sync = Mock()
        sync.get.return_value = {
            'total_count': 1,
            'workflow_runs': [
                {'id': 43, 'name': 'functional-compute',
                 'html_url': 'http://x/43',
                 'status': 'completed', 'conclusion': 'action_required',
                 'created_at': '2024-01-01T10:00:00Z',
                 'updated_at': '2024-01-01T10:05:00Z'},
            ],
        }
        result = fetch_pending_workflow_approvals(sync, 'owner/repo', 'abc123')
        assert len(result) == 1
        assert result[0]['name'] == 'workflow-approval: functional-compute'
        assert result[0]['state'] == 'action_required'
        assert result[0]['run_id'] == 43

    def test_swallows_errors(self):
        """API failures return an empty list."""
        sync = Mock()
        sync.get.side_effect = Exception('boom')
        result = fetch_pending_workflow_approvals(sync, 'owner/repo', 'abc123')
        assert result == []


class TestFetchMergeQueueRule:
    """Tests for fetch_merge_queue_rule."""

    def test_ruleset_merge_queue_rule_found(self):
        """A merge_queue rule in the rules/branches response is used."""
        sync = Mock()
        sync.get.return_value = [
            {'type': 'merge_queue',
             'parameters': {'merge_method': 'SQUASH'}},
        ]
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': True, 'merge_method': 'squash'}
        sync.graphql.assert_not_called()

    def test_ruleset_without_merge_method_parameter(self):
        """A merge_queue rule with no merge_method parameter is still required."""
        sync = Mock()
        sync.get.return_value = [
            {'type': 'merge_queue', 'parameters': {}},
        ]
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': True, 'merge_method': None}

    def test_ignores_non_merge_queue_rules(self):
        """Other rule types don't set required."""
        sync = Mock()
        sync.get.return_value = [
            {'type': 'pull_request', 'parameters': {}},
        ]
        sync.graphql.return_value = {}
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': False, 'merge_method': None}

    def test_no_rules_falls_back_to_graphql(self):
        """No merge_queue ruleset: fall back to the classic-protection check."""
        sync = Mock()
        sync.get.return_value = []
        sync.graphql.return_value = {
            'repository': {
                'mergeQueue': {'configuration': {'mergeMethod': 'REBASE'}},
            },
        }
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': True, 'merge_method': 'rebase'}
        sync.graphql.assert_called_once()

    def test_none_response_falls_back_to_graphql(self):
        """A None rules response (e.g. 403/404) is treated like an empty list."""
        sync = Mock()
        sync.get.return_value = None
        sync.graphql.return_value = {}
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': False, 'merge_method': None}
        sync.graphql.assert_called_once()

    def test_get_exception_returns_default(self):
        """An exception fetching branch rules is treated as no merge queue."""
        sync = Mock()
        sync.get.side_effect = Exception('boom')
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': False, 'merge_method': None}
        sync.graphql.assert_not_called()

    def test_propagates_offline_error(self):
        """OfflineError from branch rules fetch is not swallowed."""
        sync = Mock()
        sync.get.side_effect = OfflineError('Received 503 status code')
        with pytest.raises(OfflineError):
            fetch_merge_queue_rule(sync, 'owner/repo', 'main')

    def test_propagates_rate_limit_error(self):
        """RateLimitError from branch rules fetch is not swallowed."""
        sync = Mock()
        sync.get.side_effect = RateLimitError('Rate limit exceeded')
        with pytest.raises(RateLimitError):
            fetch_merge_queue_rule(sync, 'owner/repo', 'main')

    def test_permission_denied_403_falls_back_to_graphql(self):
        """A non-rate-limit 403 triggers _PermissionDenied and GraphQL fallback."""
        sync = Mock()

        # Make sync.get invoke the response_callback with a 403
        # response, which triggers the internal _PermissionDenied
        # exception and the GraphQL fallback path.
        forbidden = Mock()
        forbidden.status_code = 403
        forbidden.text = 'Resource not accessible by integration'
        forbidden.headers = {}

        def get_side_effect(path, **kwargs):
            cb = kwargs.get('response_callback')
            if cb:
                cb(forbidden)
            return None

        sync.get.side_effect = get_side_effect
        sync.graphql.return_value = {
            'repository': {
                'mergeQueue': {'configuration': {'mergeMethod': 'SQUASH'}},
            },
        }
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': True, 'merge_method': 'squash'}
        sync.graphql.assert_called_once()

    def test_permission_denied_404_falls_back_to_graphql(self):
        """A 404 response triggers _PermissionDenied and GraphQL fallback."""
        sync = Mock()

        not_found = Mock()
        not_found.status_code = 404
        not_found.text = 'Not Found'
        not_found.headers = {}

        def get_side_effect(path, **kwargs):
            cb = kwargs.get('response_callback')
            if cb:
                cb(not_found)
            return None

        sync.get.side_effect = get_side_effect
        sync.graphql.return_value = {}
        result = fetch_merge_queue_rule(sync, 'owner/repo', 'main')
        assert result == {'required': False, 'merge_method': None}
        sync.graphql.assert_called_once()


class TestFetchClassicMergeQueueViaGraphql:
    """Tests for _fetch_classic_merge_queue_via_graphql."""

    def test_no_slash_in_repository_name_returns_default(self):
        """A malformed repository name skips the GraphQL call entirely."""
        sync = Mock()
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'not-a-full-name', 'main', default)
        assert result is default
        sync.graphql.assert_not_called()

    def test_merge_queue_present_normalizes_method(self):
        """An active queue returns required=True with a lowercased method."""
        sync = Mock()
        sync.graphql.return_value = {
            'repository': {
                'mergeQueue': {'configuration': {'mergeMethod': 'MERGE'}},
            },
        }
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'owner/repo', 'main', default)
        assert result == {'required': True, 'merge_method': 'merge'}
        sync.graphql.assert_called_once()
        variables = sync.graphql.call_args[0][1]
        assert variables == {'owner': 'owner', 'name': 'repo', 'branch': 'main'}

    def test_merge_queue_present_without_configuration(self):
        """An active queue with no configuration still reports required=True."""
        sync = Mock()
        sync.graphql.return_value = {
            'repository': {'mergeQueue': {'configuration': None}},
        }
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'owner/repo', 'main', default)
        assert result == {'required': True, 'merge_method': None}

    def test_no_merge_queue_returns_default(self):
        """A null mergeQueue means no classic branch-protection queue."""
        sync = Mock()
        sync.graphql.return_value = {'repository': {'mergeQueue': None}}
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'owner/repo', 'main', default)
        assert result is default

    def test_missing_repository_returns_default(self):
        """A response with no repository key is handled gracefully."""
        sync = Mock()
        sync.graphql.return_value = {}
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'owner/repo', 'main', default)
        assert result is default

    def test_graphql_exception_returns_default(self):
        """An exception from the GraphQL call is treated as no merge queue."""
        sync = Mock()
        sync.graphql.side_effect = Exception('boom')
        default = {'required': False, 'merge_method': None}
        result = _fetch_classic_merge_queue_via_graphql(
            sync, 'owner/repo', 'main', default)
        assert result is default

    def test_propagates_offline_error(self):
        """OfflineError from GraphQL call is not swallowed."""
        sync = Mock()
        sync.graphql.side_effect = OfflineError('Received 502 status code')
        default = {'required': False, 'merge_method': None}
        with pytest.raises(OfflineError):
            _fetch_classic_merge_queue_via_graphql(
                sync, 'owner/repo', 'main', default)

    def test_propagates_rate_limit_error(self):
        """RateLimitError from GraphQL call is not swallowed."""
        sync = Mock()
        sync.graphql.side_effect = RateLimitError('Rate limit exceeded')
        default = {'required': False, 'merge_method': None}
        with pytest.raises(RateLimitError):
            _fetch_classic_merge_queue_via_graphql(
                sync, 'owner/repo', 'main', default)
