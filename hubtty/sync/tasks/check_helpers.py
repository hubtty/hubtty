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

from ..exceptions import OfflineError, RateLimitError

if TYPE_CHECKING:
    from ..sync import Sync

log = logging.getLogger(__name__)

# Author associations whose workflows always auto-run (org insiders).
# CONTRIBUTOR is excluded because repos using "Require approval for
# all outside collaborators" still gate them.
_TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({'MEMBER', 'COLLABORATOR', 'OWNER'})


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
    elif check['state'] == 'skipped':
        check['message'] = 'Job skipped'
    elif check['state'] == 'cancelled':
        check['message'] = 'Job cancelled'
    else:
        check['message'] = 'Job triggered'

    started = remote_check.get('started_at')
    if started:
        check['created'] = started
        check['updated'] = started
        if check['state'] not in ('skipped', 'cancelled'):
            check['started'] = started
    finished = remote_check.get('completed_at')
    if finished:
        check['updated'] = finished
        if check['state'] not in ('skipped', 'cancelled'):
            check['finished'] = finished

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
                check_data['state'], created, created,
                run_id=check_data.get('run_id'),
            )
            local_checks[check_data['name']] = check
        check.updated = dateutil.parser.parse(check_data['updated'])
        check.state = check_data['state']
        check.url = check_data['url']
        check.message = check_data['message']
        check.run_id = check_data.get('run_id')

        started = check_data.get('started')
        if started:
            check.started = dateutil.parser.parse(check_data['started'])
        finished = check_data.get('finished')
        if finished:
            check.finished = dateutil.parser.parse(check_data['finished'])


def fetch_checks(sync: 'Sync', repository_name: str,
                 commit_sha: str,
                 use_etag: bool = True,
                 author_association: str = None) -> List[Dict[str, Any]]:
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
    # Collect from both APIs into a dict keyed by name so that
    # duplicates (same CI job reported via both APIs) are merged.
    # Check-runs are processed second so they overwrite statuses
    # when both exist, since check-runs carry richer data
    # (started/finished timestamps, etc.).
    checks_by_name: Dict[str, Dict[str, Any]] = {}

    remote_commit_status = sync.get(
        f'repos/{repository_name}/commits/{commit_sha}/status',
        use_etag=use_etag,
    )
    if remote_commit_status is not None:
        for check in remote_commit_status['statuses']:
            result = check_result_from_status(check)
            checks_by_name[result['name']] = result

    remote_commit_check_runs = sync.get(
        f'repos/{repository_name}/commits/{commit_sha}/check-runs?per_page=100',
        use_etag=use_etag,
    )
    if remote_commit_check_runs is not None:
        for check in remote_commit_check_runs:
            result = check_result_from_check_run(check)
            checks_by_name[result['name']] = result

    # Pending-approval workflow runs aren't in either API above.
    # Skip for trusted authors whose workflows always auto-run.
    if author_association not in _TRUSTED_AUTHOR_ASSOCIATIONS:
        for result in fetch_pending_workflow_approvals(
                sync, repository_name, commit_sha, use_etag=use_etag):
            checks_by_name[result['name']] = result

    return list(checks_by_name.values())


def fetch_pending_workflow_approvals(sync: 'Sync', repository_name: str,
                                     commit_sha: str,
                                     use_etag: bool = True) -> List[Dict[str, Any]]:
    """Find workflow runs awaiting approval for a commit.

    Returns synthetic check dicts with state 'action_required' and
    run_id set, one per pending run.
    """
    try:
        runs = sync.get(
            f'repos/{repository_name}/actions/runs'
            f'?head_sha={commit_sha}&per_page=100',
            use_etag=use_etag,
        )
    except Exception:
        log.exception(
            "Unable to fetch workflow runs for %s@%s, assuming none "
            "pending approval",
            repository_name, commit_sha,
        )
        return []

    results = []
    for run in (runs or {}).get('workflow_runs', []):
        # GitHub flags pending approval via status or conclusion
        # being 'action_required'; check both since the docs are
        # ambiguous about which applies when.
        if 'action_required' not in {run.get('status'), run.get('conclusion')}:
            continue
        results.append({
            'name': 'workflow-approval: %s' % (
                run.get('name') or f'workflow run {run["id"]}'),
            'url': run.get('html_url', ''),
            'state': 'action_required',
            'message': 'Waiting for a maintainer to approve this '
                       'workflow run',
            'created': run['created_at'],
            'updated': run['updated_at'],
            'run_id': run['id'],
        })
    return results


def fetch_merge_queue_rule(sync: 'Sync', repository_name: str,
                           branch_name: str) -> Dict[str, Any]:
    """Fetch the effective merge-queue rule (if any) for a branch.

    Uses ``GET /repos/{owner}/{repo}/rules/branches/{branch}``, which
    returns the *effective* rules for the branch merged from classic
    branch protection and any applicable rulesets. Requires at least
    read access; tokens without sufficient permission (or repos with
    no rules configured) may get a 403/404, which is treated as "no
    merge queue" rather than a sync failure.

    This only catches merge queues configured via *rulesets*. GitHub
    also lets repos require a merge queue via the older, classic
    "Require merge queue" branch-protection checkbox, and that setting
    is not exposed on the branch-protection-rule object by either REST
    or GraphQL (a documented GitHub API gap -- see
    https://github.com/orgs/community/discussions/170601). The only
    way to detect *that* case is indirectly, via GraphQL's
    ``repository.mergeQueue(branch:)``: it returns a real object (with
    the queue's configuration) if a queue is active for the branch,
    and ``null`` otherwise. So that's used here as a fallback when the
    REST rules lookup finds nothing.

    Args:
        sync: The Sync instance to use for API calls.
        repository_name: Full repository name (e.g. 'owner/repo').
        branch_name: The base branch name (e.g. 'main').

    Returns:
        A dict with ``required`` (bool) and ``merge_method`` (one of
        ``'merge'``/``'squash'``/``'rebase'``, or None if unknown).
    """
    result = {'required': False, 'merge_method': None}

    class _PermissionDenied(Exception):
        """Raised when the branch-rules endpoint returns 403/404."""

    def ignore_permission_errors(response):
        if response.status_code == 403:
            # Catch secondary/abuse rate limits that bypass the
            # primary handler (no X-RateLimit-Remaining header).
            body = response.text.lower()
            if 'rate limit' in body or 'abuse' in body:
                raise RateLimitError(
                    "Rate limit exceeded (status %d)" % response.status_code)
            raise _PermissionDenied(response.status_code)
        if response.status_code == 404:
            raise _PermissionDenied(response.status_code)
        sync.checkResponse(response)

    try:
        rules = sync.get(
            f'repos/{repository_name}/rules/branches/{branch_name}',
            use_etag=True,
            response_callback=ignore_permission_errors,
        )
    except _PermissionDenied:
        log.debug(
            "Permission denied fetching branch rules for %s@%s, "
            "falling back to GraphQL",
            repository_name, branch_name,
        )
        return _fetch_classic_merge_queue_via_graphql(
            sync, repository_name, branch_name, result)
    except (OfflineError, RateLimitError):
        raise
    except Exception:
        log.warning(
            "Unable to fetch branch rules for %s@%s, assuming no merge queue",
            repository_name, branch_name,
        )
        return result

    for rule in rules or []:
        if rule.get('type') == 'merge_queue':
            result['required'] = True
            # Normalize to lowercase to match Hubtty's convention.
            method = (rule.get('parameters') or {}).get('merge_method')
            result['merge_method'] = method.lower() if method else None
            break

    if not result['required']:
        result = _fetch_classic_merge_queue_via_graphql(
            sync, repository_name, branch_name, result)

    return result


def _fetch_classic_merge_queue_via_graphql(sync, repository_name, branch_name,
                                           default_result):
    """Fallback merge-queue check for classic branch protection.

    See fetch_merge_queue_rule()'s docstring for why this is needed.
    """
    if '/' not in repository_name:
        return default_result
    owner, name = repository_name.split('/', 1)
    query = """
    query($owner: String!, $name: String!, $branch: String!) {
      repository(owner: $owner, name: $name) {
        mergeQueue(branch: $branch) {
          configuration { mergeMethod }
        }
      }
    }
    """
    try:
        data = sync.graphql(query, {
            'owner': owner, 'name': name, 'branch': branch_name,
        })
    except (OfflineError, RateLimitError):
        raise
    except Exception:
        log.warning(
            "Unable to check classic merge-queue status for %s@%s via "
            "GraphQL, assuming no merge queue",
            repository_name, branch_name,
        )
        return default_result

    merge_queue = (data.get('repository') or {}).get('mergeQueue')
    if not merge_queue:
        return default_result

    method = (merge_queue.get('configuration') or {}).get('mergeMethod')
    return {
        'required': True,
        'merge_method': method.lower() if method else None,
    }


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
