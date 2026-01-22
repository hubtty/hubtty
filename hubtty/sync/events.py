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

"""Update events for sync operations.

These events are used to notify the UI about changes that occurred during
synchronization.
"""

from dataclasses import dataclass, field
from typing import Set, TYPE_CHECKING

if TYPE_CHECKING:
    from hubtty.db import PullRequest, Session


class UpdateEvent:
    """Base class for sync update events."""

    def updateRelatedPullRequests(self, session: 'Session', pr: 'PullRequest') -> None:
        """Update the related_pr_keys set with PRs related to this one.

        Args:
            session: Database session.
            pr: The pull request to find related PRs for.
        """
        related_pr_keys: Set[int] = set()
        related_pr_keys.add(pr.key)
        for commit in pr.commits:
            parent = pr.getCommitBySha(commit.parent)
            if parent:
                related_pr_keys.add(parent.pull_request.key)
            for child in session.getCommitsByParent(commit.commit):
                related_pr_keys.add(child.pull_request.key)
        self.related_pr_keys = related_pr_keys


@dataclass
class RepositoryAddedEvent(UpdateEvent):
    """Event emitted when a new repository is added to the local database."""

    repository_key: int

    def __repr__(self) -> str:
        return f'<RepositoryAddedEvent repository_key:{self.repository_key}>'


@dataclass
class PullRequestAddedEvent(UpdateEvent):
    """Event emitted when a new pull request is added to the local database."""

    repository_key: int
    pr_key: int
    related_pr_keys: Set[int] = field(default_factory=set)
    review_flag_changed: bool = True
    state_changed: bool = True
    held_changed: bool = False

    def __repr__(self) -> str:
        return (
            f'<PullRequestAddedEvent repository_key:{self.repository_key} '
            f'pr_key:{self.pr_key}>'
        )


@dataclass
class PullRequestUpdatedEvent(UpdateEvent):
    """Event emitted when an existing pull request is updated."""

    repository_key: int
    pr_key: int
    related_pr_keys: Set[int] = field(default_factory=set)
    review_flag_changed: bool = False
    state_changed: bool = False
    held_changed: bool = False

    def __repr__(self) -> str:
        return (
            f'<PullRequestUpdatedEvent repository_key:{self.repository_key} '
            f'pr_key:{self.pr_key} review_flag_changed:{self.review_flag_changed} '
            f'state_changed:{self.state_changed}>'
        )
