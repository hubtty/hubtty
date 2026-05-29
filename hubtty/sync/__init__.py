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

"""
Sync package - handles GitHub API synchronization.

This module provides the Sync class for synchronizing data between
GitHub and the local database, along with various Task classes for
specific sync operations.
"""

# Constants
from .constants import HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY, TIMEOUT

# Exceptions
from .exceptions import OfflineError, RestrictedError, RateLimitError

# Core classes
from .queue import MultiQueue
from .task import Task
from .sync import Sync

# Events
from .events import (
    UpdateEvent,
    RepositoryAddedEvent,
    PullRequestAddedEvent,
    PullRequestUpdatedEvent,
)

# Account tasks
from .tasks.account import SyncOwnAccountTask, SyncAccountTask

# Repository tasks
from .tasks.repository import (
    SyncRepositoryListTask,
    SyncSubscribedRepositoryBranchesTask,
    SyncRepositoryBranchesTask,
    SyncSubscribedRepositoryLabelsTask,
    SyncRepositoryLabelsTask,
    SyncSubscribedRepositoriesTask,
    SyncRepositoryTask,
    SetRepositoryUpdatedTask,
)

# Pull request tasks
from .tasks.pull_request import SyncPullRequestTask, SyncOutdatedPullRequestsTask

# Upload tasks
from .tasks.upload import (
    UploadReviewsTask,
    SetLabelsTask,
    RebasePullRequestTask,
    EditPullRequestTask,
    UploadReviewTask,
    SendMergeTask,
)

# Maintenance tasks
from .tasks.maintenance import (
    PruneDatabaseTask,
    PrunePullRequestTask,
    VacuumDatabaseTask,
)

# Repository check tasks
from .tasks.repository_check import CheckReposTask, CheckCommitsTask

__all__ = [
    # Constants
    'HIGH_PRIORITY',
    'NORMAL_PRIORITY',
    'LOW_PRIORITY',
    'TIMEOUT',
    # Exceptions
    'OfflineError',
    'RestrictedError',
    'RateLimitError',
    # Core classes
    'MultiQueue',
    'Task',
    'Sync',
    # Events
    'UpdateEvent',
    'RepositoryAddedEvent',
    'PullRequestAddedEvent',
    'PullRequestUpdatedEvent',
    # Account tasks
    'SyncOwnAccountTask',
    'SyncAccountTask',
    # Repository tasks
    'SyncRepositoryListTask',
    'SyncSubscribedRepositoryBranchesTask',
    'SyncRepositoryBranchesTask',
    'SyncSubscribedRepositoryLabelsTask',
    'SyncRepositoryLabelsTask',
    'SyncSubscribedRepositoriesTask',
    'SyncRepositoryTask',
    'SetRepositoryUpdatedTask',
    # Pull request tasks
    'SyncPullRequestTask',
    'SyncOutdatedPullRequestsTask',
    # Upload tasks
    'UploadReviewsTask',
    'SetLabelsTask',
    'RebasePullRequestTask',
    'EditPullRequestTask',
    'UploadReviewTask',
    'SendMergeTask',
    # Maintenance tasks
    'PruneDatabaseTask',
    'PrunePullRequestTask',
    'VacuumDatabaseTask',
    # Repository check tasks
    'CheckReposTask',
    'CheckCommitsTask',
]
