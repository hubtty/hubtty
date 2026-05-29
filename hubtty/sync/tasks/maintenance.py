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

"""Database maintenance tasks."""

import errno
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from hubtty import gitrepo
from ..task import Task

if TYPE_CHECKING:
    from ..sync import Sync


@dataclass
class PruneDatabaseTask(Task):
    """Prune old closed pull requests from the database."""

    age: Optional[str]

    def run(self, sync: 'Sync') -> None:
        """Prune old pull requests based on age.

        Args:
            sync: The Sync instance to use for API calls.
        """
        if not self.age:
            return
        app = sync.app
        with app.db.getSession() as session:
            for pr in session.getPullRequests(f'state:closed age:{self.age}'):
                t = PrunePullRequestTask(pr.key, priority=self.priority)
                self.tasks.append(t)
                sync.submitTask(t)
        t = VacuumDatabaseTask(priority=self.priority)
        self.tasks.append(t)
        sync.submitTask(t)


@dataclass
class PrunePullRequestTask(Task):
    """Prune a specific pull request from the database and git repo."""

    key: int

    def run(self, sync: 'Sync') -> None:
        """Delete a pull request and its git refs.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.key)
            if not pr:
                return
            repo = gitrepo.get_repo(pr.repository.name, app.config)
            self.log.info(
                "Pruning %s pull request %s state:%s updated:%s",
                pr.repository.name, pr.number, pr.state, pr.updated
            )
            pr_ref = f"pull/{pr.number}/head"
            self.log.info("Deleting %s ref %s", pr.repository.name, pr_ref)
            try:
                repo.deleteRef(pr_ref)
            except OSError as e:
                if e.errno not in [errno.EISDIR, errno.EPERM]:
                    raise
            session.delete(pr)


@dataclass
class VacuumDatabaseTask(Task):
    """Vacuum the database to reclaim space."""

    def run(self, sync: 'Sync') -> None:
        """Run database vacuum.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            session.vacuum()
