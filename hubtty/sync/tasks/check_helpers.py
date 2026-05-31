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

"""Shared helper functions for CI check synchronization."""

import logging
from typing import Any, Dict, List, TYPE_CHECKING

import dateutil.parser

if TYPE_CHECKING:
    from ..sync import Sync

log = logging.getLogger(__name__)


def check_result_from_check_run(remote_check: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a GitHub check run to internal format.

    Args:
        remote_check: Check run data from GitHub API.

    Returns:
        Normalized check data dictionary.
    """
    check = {}
    check['name'] = remote_check['name']
    check['url'] = remote_check.get('html_url', '')
    if remote_check['status'] == 'completed':
        check['state'] = remote_check['conclusion']
    else:
        check['state'] = 'pending'
    # Set message according to status
    if check['state'] == 'success':
        check['message'] = 'Job succeeded'
    elif check['state'] == 'failure':
        check['message'] = 'Job failed'
    else:
        check['message'] = 'Job triggered'

    started = remote_check.get('started_at')
    if started:
        check['started'] = started
        check['created'] = started
        check['updated'] = started
    finished = remote_check.get('completed_at')
    if finished:
        check['finished'] = finished
        check['updated'] = finished

    return check


def check_result_from_status(remote_check: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a GitHub commit status to internal format.

    Args:
        remote_check: Commit status data from GitHub API.

    Returns:
        Normalized check data dictionary.
    """
    check = {}
    check['name'] = remote_check['context']
    check['url'] = remote_check.get('target_url', '')
    check['state'] = remote_check['state']
    check['message'] = remote_check.get('description', '')

    check['created'] = remote_check['created_at']
    check['updated'] = remote_check['updated_at']

    return check


def update_checks(session, commit, remote_checks_data: List[Dict[str, Any]]) -> None:
    """Update checks for a commit.

    Args:
        session: Database session.
        commit: The commit to update checks for.
        remote_checks_data: List of check data from GitHub.
    """
    # Delete outdated checks
    remote_check_names = [c['name'] for c in remote_checks_data]
    for check in commit.checks:
        if check.name not in remote_check_names:
            log.info("Deleted check %s", check.key)
            session.delete(check)

    local_checks = {c.name: c for c in commit.checks}
    for check_data in remote_checks_data:
        check = local_checks.get(check_data['name'])
        if check is None:
            created = dateutil.parser.parse(check_data['created'])
            log.info(
                "Creating check %s on commit %s",
                check_data['name'], commit.key
            )
            check = commit.createCheck(
                check_data['name'],
                check_data['state'], created, created
            )
        check.updated = dateutil.parser.parse(check_data['updated'])
        check.state = check_data['state']
        check.url = check_data['url']
        check.message = check_data['message']

        started = check_data.get('started')
        if started:
            check.started = dateutil.parser.parse(check_data['started'])
        finished = check_data.get('finished')
        if finished:
            check.finished = dateutil.parser.parse(check_data['finished'])


def fetch_checks(sync: 'Sync', repository_name: str,
                 commit_sha: str,
                 use_etag: bool = True) -> List[Dict[str, Any]]:
    """Fetch CI checks for a commit from GitHub.

    Fetches both commit statuses and check runs, normalizing them
    into a common format.  Uses conditional requests (ETags) by
    default so that repeated polls for the same commit are cheap.

    Args:
        sync: The Sync instance to use for API calls.
        repository_name: Full repository name (e.g. 'owner/repo').
        commit_sha: The commit SHA to fetch checks for.
        use_etag: Enable conditional requests via ETag / If-None-Match.

    Returns:
        List of normalized check data dictionaries.
    """
    checks = []
    remote_commit_status = sync.get(
        f'repos/{repository_name}/commits/{commit_sha}/status',
        use_etag=use_etag,
    )
    if remote_commit_status is not None:
        for check in remote_commit_status['statuses']:
            checks.append(check_result_from_status(check))

    remote_commit_check_runs = sync.get(
        f'repos/{repository_name}/commits/{commit_sha}/check-runs',
        use_etag=use_etag,
    )
    if remote_commit_check_runs is not None:
        for check in remote_commit_check_runs['check_runs']:
            checks.append(check_result_from_check_run(check))

    return checks


def has_pending_checks(checks_data: List[Dict[str, Any]],
                       ignore_names: frozenset = frozenset()) -> bool:
    """Check if any checks are still in pending state.

    Args:
        checks_data: List of normalized check data dictionaries.
        ignore_names: Set of check names whose pending state should
            be ignored (e.g. merge-gate contexts like ``tide`` that
            stay pending until labels are applied).

    Returns:
        True if any check has state 'pending' and is not ignored.
    """
    return any(c['state'] == 'pending' and c['name'] not in ignore_names
               for c in checks_data)
