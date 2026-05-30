# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from hubtty.sync.tasks.check_helpers import (
    check_result_from_check_run,
    check_result_from_status,
    fetch_checks,
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
            # check runs response
            {'check_runs': [
                {'name': 'ci/check', 'html_url': 'http://y',
                 'status': 'completed', 'conclusion': 'failure',
                 'started_at': '2024-01-01T10:00:00Z',
                 'completed_at': '2024-01-01T10:03:00Z'},
            ]},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert len(result) == 2
        assert result[0]['name'] == 'ci/status'
        assert result[0]['state'] == 'success'
        assert result[1]['name'] == 'ci/check'
        assert result[1]['state'] == 'failure'

        # Verify API calls
        assert sync.get.call_count == 2
        sync.get.assert_any_call(
            'repos/owner/repo/commits/abc123/status', use_etag=True)
        sync.get.assert_any_call(
            'repos/owner/repo/commits/abc123/check-runs', use_etag=True)

    def test_empty_statuses_and_check_runs(self):
        """Returns empty list when no checks exist."""
        sync = Mock()
        sync.get.side_effect = [
            {'statuses': []},
            {'check_runs': []},
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
            {'check_runs': []},
        ]
        result = fetch_checks(sync, 'owner/repo', 'abc123')
        assert len(result) == 1
        assert result[0]['name'] == 'ci/only'


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
        )
        assert new_check.state == 'success'
        assert new_check.url == 'http://x'
        assert new_check.message == 'Job succeeded'

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
