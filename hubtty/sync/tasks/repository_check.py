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

"""Repository checking tasks for startup validation."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hubtty import gitrepo
from ..task import Task
from ..constants import LOW_PRIORITY

if TYPE_CHECKING:
    from ..sync import Sync


@dataclass
class CheckReposTask(Task):
    """Check all subscribed repositories on startup.

    For any subscribed repository without a local repo or if
    --fetch-missing-refs is supplied, check all local pull requests for
    missing refs, and sync the associated pull requests.
    """

    def run(self, sync: 'Sync') -> None:
        """Check repositories and submit sync tasks for missing refs.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            repositories = session.getRepositories(subscribed=True)
        for repository in repositories:
            try:
                missing = False
                try:
                    gitrepo.get_repo(repository.name, app.config)
                except gitrepo.GitCloneError:
                    missing = True
                if missing or app.fetch_missing_refs:
                    sync.submitTask(
                        CheckCommitsTask(
                            repository.key,
                            force_fetch=app.fetch_missing_refs,
                            priority=LOW_PRIORITY
                        )
                    )
            except Exception:
                self.log.exception("Exception checking repo %s", repository.name)


@dataclass
class CheckCommitsTask(Task):
    """Check commits in a repository for missing refs."""

    repository_key: int
    force_fetch: bool = field(default=False, compare=False)

    def run(self, sync: 'Sync') -> None:
        """Check for missing commits and submit sync tasks.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app
        to_sync = set()
        with app.db.getSession() as session:
            repository = session.getRepository(self.repository_key)
            repo = None
            try:
                repo = gitrepo.get_repo(repository.name, app.config)
            except gitrepo.GitCloneError:
                pass
            for pr in repository.open_prs:
                if repo:
                    for commit in pr.commits:
                        shas_to_check = [s for s in (commit.parent, commit.sha)
                                         if s != gitrepo.EMPTY_TREE_SHA]
                        if shas_to_check and repo.checkCommits(shas_to_check):
                            to_sync.add(pr.pr_id)
                else:
                    to_sync.add(pr.pr_id)
        for pr_id in to_sync:
            sync.submitTask(
                SyncPullRequestTask(
                    pr_id,
                    force_fetch=self.force_fetch,
                    priority=self.priority
                )
            )
