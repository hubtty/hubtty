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

"""Repository synchronization tasks."""

import datetime
from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING

from ..task import Task
from ..events import RepositoryAddedEvent
from ..exceptions import OfflineError
from .check_helpers import fetch_merge_queue_rule

if TYPE_CHECKING:
    from ..sync import Sync


def _coalesce(d, key, default):
    """Return ``d[key]`` if present and not None, else *default*."""
    v = d.get(key)
    return v if v is not None else default


@dataclass
class SyncRepositoryListTask(Task):
    """Sync the list of repositories the user has access to."""

    def run(self, sync: 'Sync') -> None:
        """Fetch and sync all accessible repositories.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app

        remote_repos = sync.get('user/repos?per_page=100')
        remote_repos_names = [r['full_name'] for r in remote_repos]

        def checkResponse(response):
            self.log.debug('HTTP status code: %d', response.status_code)
            if response.status_code == 503:
                raise OfflineError("Received 503 status code")
            elif response.status_code == 404:
                self.log.error(
                    'Repository %s does not exist or you do not have '
                    'the permissions to view it.', additional_repo
                )
            elif response.status_code >= 400:
                raise Exception(
                    f"Received {response.status_code} status code: {response.text}"
                )

        # Add additional repos
        for additional_repo in sync.app.config.additional_repositories:
            if additional_repo not in remote_repos_names:
                remote_repo = sync.get(
                    f'repos/{additional_repo}',
                    response_callback=checkResponse
                )
                if remote_repo:
                    remote_repos.append(remote_repo)
                    remote_repos_names.append(additional_repo)

        with app.db.getSession() as session:
            for remote_repo in remote_repos:
                repo_name = remote_repo['full_name']
                repo_desc = (remote_repo.get('description', '') or '').replace('\r', '')
                repository = session.getRepositoryByName(repo_name)
                if not repository:
                    repository = session.createRepository(repo_name, description=repo_desc)
                    self.log.info("Created repository %s", repo_name)
                    self.results.append(RepositoryAddedEvent(repository.key))
                repository.description = repo_desc
                repository.can_push = remote_repo['permissions']['push']
                # GitHub's bulk listing returns these as null; coalesce
                # to defaults. Real values are fetched per-repo in
                # SyncRepositoryBranchesTask for subscribed repos.
                repository.allow_merge_commit = _coalesce(
                    remote_repo, 'allow_merge_commit', True)
                repository.allow_squash_merge = _coalesce(
                    remote_repo, 'allow_squash_merge', True)
                repository.allow_rebase_merge = _coalesce(
                    remote_repo, 'allow_rebase_merge', True)
                repository.allow_auto_merge = _coalesce(
                    remote_repo, 'allow_auto_merge', False)

            for p in session.getRepositories():
                if p.name not in remote_repos_names:
                    self.log.info("Deleted repository %s", p.name)
                    session.delete(p)


@dataclass
class SyncSubscribedRepositoryBranchesTask(Task):
    """Sync branches for all subscribed repositories."""

    def run(self, sync: 'Sync') -> None:
        """Submit branch sync tasks for all subscribed repositories.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            repositories = session.getRepositories(subscribed=True)
        for p in repositories:
            sync.submitTask(SyncRepositoryBranchesTask(p.name, priority=self.priority))


@dataclass
class SyncRepositoryBranchesTask(Task):
    """Sync branches and merge settings for a specific repository.

    This task also fetches the repository's merge-method flags
    (allow_merge_commit/allow_squash_merge/allow_rebase_merge/
    allow_auto_merge) from the single-repo endpoint, because the bulk
    ``GET /user/repos`` listing always returns them as ``null``.
    Combining this with the branch sync avoids a separate task and
    keeps merge-method and merge-queue data in sync.
    """

    repository_name: str

    def run(self, sync: 'Sync') -> None:
        """Sync branches and merge settings for the repository.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app

        # Fetch merge-method settings from the single-repo endpoint.
        remote_repo = sync.get(f'repos/{self.repository_name}',
                               use_etag=True)

        remote = sync.get(f'repos/{self.repository_name}/branches?per_page=100',
                         use_etag=True)
        remote = remote or []
        remote_branches = set()
        for b in remote:
            remote_branches.add(b['name'])
        with app.db.getSession() as session:
            repository = session.getRepositoryByName(self.repository_name)

            # Update merge-method flags (empty dict on 304 Not Modified).
            if remote_repo and repository:
                repository.allow_merge_commit = _coalesce(
                    remote_repo, 'allow_merge_commit', True)
                repository.allow_squash_merge = _coalesce(
                    remote_repo, 'allow_squash_merge', True)
                repository.allow_rebase_merge = _coalesce(
                    remote_repo, 'allow_rebase_merge', True)
                repository.allow_auto_merge = _coalesce(
                    remote_repo, 'allow_auto_merge', False)

            local = {}
            for branch in repository.branches:
                local[branch.name] = branch
            local_branches = set(local.keys())

            for name in local_branches - remote_branches:
                session.delete(local[name])
                self.log.info(
                    "Deleted branch %s from repository %s in local DB.",
                    name, repository.name
                )

            for name in remote_branches - local_branches:
                repository.createBranch(name)
                self.log.info(
                    "Added branch %s to repository %s in local DB.",
                    name, repository.name
                )

            # Refresh to include newly created branches.
            local = {b.name: b for b in repository.branches}

            # Only check branches that are the base of an open PR
            # to avoid exhausting the API rate limit.
            pr_base_branches = {
                pr.branch for pr in repository.pull_requests
                if pr.state == 'open'
            }
            branches_to_check = [
                name for name in local if name in pr_base_branches
            ]

        # Fetch merge-queue rules outside the db session.
        merge_queue_rules = {}
        for name in branches_to_check:
            merge_queue_rules[name] = fetch_merge_queue_rule(
                sync, self.repository_name, name)

        if merge_queue_rules:
            with app.db.getSession() as session:
                repository = session.getRepositoryByName(
                    self.repository_name)
                local = {b.name: b for b in repository.branches}
                for name, rule in merge_queue_rules.items():
                    branch = local.get(name)
                    if branch:
                        branch.merge_queue_required = rule['required']
                        branch.merge_queue_method = rule['merge_method']


@dataclass
class SyncSubscribedRepositoryLabelsTask(Task):
    """Sync labels for all subscribed repositories."""

    def run(self, sync: 'Sync') -> None:
        """Submit label sync tasks for all subscribed repositories.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            repositories = session.getRepositories(subscribed=True)
        for p in repositories:
            sync.submitTask(SyncRepositoryLabelsTask(p.name, priority=self.priority))


@dataclass
class SyncRepositoryLabelsTask(Task):
    """Sync labels for a specific repository."""

    repository_name: str

    def run(self, sync: 'Sync') -> None:
        """Sync labels for the repository.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        remote_labels = sync.get(f'repos/{self.repository_name}/labels',
                                   use_etag=True)
        with app.db.getSession() as session:
            repository = session.getRepositoryByName(self.repository_name)

            for remote_label in remote_labels:
                label = session.getLabel(remote_label['id'])
                if not label:
                    self.log.info(
                        "Created label %s for repository %s",
                        remote_label['name'], repository.name
                    )
                    repository.createLabel(
                        remote_label['id'], remote_label['name'],
                        remote_label['color'], remote_label['description']
                    )
                    app.registerPaletteEntry(remote_label['id'], remote_label['color'])
                else:
                    label.name = remote_label['name']
                    label.color = remote_label['color']
                    label.description = remote_label['description']

            # Delete old labels
            remote_label_ids = [label['id'] for label in remote_labels]
            for label in repository.labels:
                if label.id not in remote_label_ids:
                    self.log.info("Deleted label %s", label.name)
                    session.delete(label)


@dataclass
class SyncSubscribedRepositoriesTask(Task):
    """Sync all subscribed repositories."""

    def run(self, sync: 'Sync') -> None:
        """Submit sync tasks for all subscribed repositories.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            keys = [p.key for p in session.getRepositories(subscribed=True)]
        # Sync repositories at most 10 at a time
        for i in range(0, len(keys), 10):
            t = SyncRepositoryTask(keys[i:i + 10], priority=self.priority)
            self.tasks.append(t)
            sync.submitTask(t)


@dataclass
class SyncRepositoryTask(Task):
    """Sync pull requests for specific repositories."""

    repository_keys: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Handle single key passed as int."""
        super().__post_init__()
        if isinstance(self.repository_keys, int):
            self.repository_keys = [self.repository_keys]

    def run(self, sync: 'Sync') -> None:
        """Sync pull requests for the repositories.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app
        now = datetime.datetime.utcnow()
        full_sync = []
        partial_sync = []
        sync_from = now
        with app.db.getSession() as session:
            for repository_key in self.repository_keys:
                repository = session.getRepository(repository_key)
                if repository.updated:
                    partial_sync.append(repository.name)
                    # We can use the oldest sync time of the bunch, because we
                    # sync repositories individually when subscribing to them.
                    if repository.updated < sync_from:
                        sync_from = repository.updated
                else:
                    full_sync.append(repository.name)

        def sync_repositories(repositories, query):
            base_query = query
            for repository_name in repositories:
                query += f' repo:{repository_name}'
            result = sync.query(query)
            pull_requests = result.items

            if (result.total_count is not None
                    and result.total_count > len(pull_requests)):
                # The batched query exceeded the GitHub Search API's
                # 1 000-result cap.  Fall back to per-repo queries so
                # every repository gets complete results.
                self.log.warning(
                    "Search results truncated (%d/%d). "
                    "Re-querying repositories individually.",
                    len(pull_requests), result.total_count)
                pull_requests = []
                for repository_name in repositories:
                    r = sync.query(
                        f'{base_query} repo:{repository_name}')
                    if (r.total_count is not None
                            and r.total_count > len(r.items)):
                        self.log.warning(
                            "Search results for %s still truncated "
                            "(%d/%d)",
                            repository_name, len(r.items),
                            r.total_count)
                    pull_requests.extend(r.items)

            pr_ids = [pr['pull_request']['url'].split('repos/')[1] for pr in pull_requests]
            with app.db.getSession() as session:
                # Winnow the list of IDs to only the ones in the local DB.
                pr_ids = session.getPullRequestIDs(pr_ids)
            for pr in pull_requests:
                pr_id = pr['pull_request']['url'].split('repos/')[1]
                # For now, just sync open PRs or PRs already
                # in the db optionally we could sync all PRs ever
                if pr_id in pr_ids or pr['state'] == 'open':
                    sync.submitTask(SyncPullRequestTask(pr_id, priority=self.priority))

        if full_sync:
            query = 'type:pr state:open'
            sync_repositories(full_sync, query)

        if partial_sync:
            # Allow 4 seconds for request time, etc.
            sync_from_iso = (sync_from - datetime.timedelta(seconds=4)).replace(microsecond=0).isoformat()
            query = f'type:pr updated:>{sync_from_iso}'
            sync_repositories(partial_sync, query)

        for key in self.repository_keys:
            sync.submitTask(SetRepositoryUpdatedTask(key, now, priority=self.priority))


@dataclass
class SetRepositoryUpdatedTask(Task):
    """Mark a repository as updated at a specific time."""

    repository_key: int
    updated: datetime.datetime

    def run(self, sync: 'Sync') -> None:
        """Set the repository's updated timestamp.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            repository = session.getRepository(self.repository_key)
            repository.updated = self.updated
