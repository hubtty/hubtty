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

"""Main Sync orchestrator class."""

import os
import queue
import threading
import time
from typing import Optional, TYPE_CHECKING

import requests
import requests.utils

import hubtty.version
from .constants import HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY
from .queue import MultiQueue
from .http import HTTPClient
from .exceptions import OfflineError, RateLimitError, RestrictedError
from .task import Task

# Import tasks
from .tasks.account import SyncOwnAccountTask
from .tasks.repository import (
    SyncRepositoryListTask,
    SyncSubscribedRepositoriesTask,
    SyncSubscribedRepositoryBranchesTask,
    SyncSubscribedRepositoryLabelsTask,
)
from .tasks.pull_request import SyncOutdatedPullRequestsTask
from .tasks.upload import UploadReviewsTask
from .tasks.repository_check import CheckReposTask
from .tasks.maintenance import PruneDatabaseTask

if TYPE_CHECKING:
    from hubtty.app import App


class Sync(HTTPClient):
    """Main sync orchestrator - manages task queue and sync thread.

    This class extends HTTPClient to provide GitHub API access, and adds
    task queue management for synchronizing data between GitHub and the
    local database.
    """

    def __init__(self, app: 'App', disable_background_sync: bool) -> None:
        """Initialize the Sync instance.

        Args:
            app: The main application instance.
            disable_background_sync: If True, don't start background sync tasks.
        """
        user_agent = 'Hubtty/{} {}'.format(
            hubtty.version.version_info.release_string(),
            requests.utils.default_user_agent()
        )
        github_api_version = '2022-11-28'

        super().__init__(app, user_agent, github_api_version)

        self.offline = False
        self.consecutive_rate_limit_errors = 0
        self.account_id: Optional[int] = None
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.result_queue: queue.Queue = queue.Queue()

        # Submit initial account sync task
        self.submitTask(SyncOwnAccountTask(priority=HIGH_PRIORITY))

        if not disable_background_sync:
            self._submit_background_tasks()
            self._start_periodic_sync()

    def _submit_background_tasks(self) -> None:
        """Submit initial background sync tasks."""
        self.submitTask(CheckReposTask(priority=HIGH_PRIORITY))
        self.submitTask(UploadReviewsTask(priority=HIGH_PRIORITY))
        self.submitTask(SyncRepositoryListTask(priority=HIGH_PRIORITY))
        self.submitTask(SyncSubscribedRepositoriesTask(priority=NORMAL_PRIORITY))
        self.submitTask(SyncSubscribedRepositoryBranchesTask(priority=LOW_PRIORITY))
        self.submitTask(SyncSubscribedRepositoryLabelsTask(priority=LOW_PRIORITY))
        self.submitTask(SyncOutdatedPullRequestsTask(priority=LOW_PRIORITY))
        self.submitTask(
            PruneDatabaseTask(self.app.config.expire_age, priority=LOW_PRIORITY)
        )

    def _start_periodic_sync(self) -> None:
        """Start the periodic sync thread."""
        self.periodic_thread = threading.Thread(target=self.periodicSync)
        self.periodic_thread.daemon = True
        self.periodic_thread.start()

    def periodicSync(self) -> None:
        """Background thread for periodic sync operations."""
        hourly = time.time()
        while True:
            try:
                time.sleep(60)
                self.syncSubscribedRepositories()
                now = time.time()
                if now - hourly > 3600:
                    hourly = now
                    self.pruneDatabase()
                    self.syncOutdatedPullRequests()
            except Exception:
                self.log.exception('Exception in periodicSync')

    def submitTask(self, task: Task) -> None:
        """Submit a task to the queue.

        Args:
            task: The task to submit.
        """
        if not self.offline:
            if not self.queue.put(task, task.priority):
                task.complete(False)
        else:
            task.complete(False)

    def run(self, pipe: int) -> None:
        """Main sync loop - run forever processing tasks.

        Args:
            pipe: File descriptor to write refresh signals to.
        """
        task = None
        while True:
            task = self._run(pipe, task)

    def _run(self, pipe: int, task: Optional[Task] = None) -> Optional[Task]:
        """Run a single task.

        Args:
            pipe: File descriptor to write refresh signals to.
            task: Task to run, or None to get next from queue.

        Returns:
            The task to retry (if offline), or None.
        """
        if not task:
            task = self.queue.get()
        self.log.debug('Run: %s', task)
        try:
            task.run(self)
            task.complete(True)
            self.queue.complete(task)
            if task.followup:
                self.submitTask(task.followup)
        except (
            requests.ConnectionError,
            OfflineError,
            RateLimitError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ReadTimeout,
        ) as e:
            self.log.warning("Offline due to: %s", e)

            # Calculate backoff time
            if isinstance(e, RateLimitError):
                backoff = self._calculate_rate_limit_backoff(e)
            else:
                backoff = 30  # Fixed backoff for non-rate-limit errors

            if not self.offline:
                self.submitTask(UploadReviewsTask(priority=HIGH_PRIORITY))
            self.offline = True
            self.app.status.update(offline=True, refresh=False)
            os.write(pipe, b'refresh\n')
            time.sleep(backoff)
            return task
        except RestrictedError as e:
            task.complete(False)
            self.queue.complete(task)
            self.log.warning("Failed to run task %s: %s", task, e)
            self.app.status.update(error=True, refresh=False)
        except Exception:
            task.complete(False)
            self.queue.complete(task)
            self.log.exception('Exception running task %s', task)
            self.app.status.update(error=True, refresh=False)
        self.offline = False
        self.consecutive_rate_limit_errors = 0
        self.app.status.update(offline=False, refresh=False)
        for r in task.results:
            self.result_queue.put(r)
        os.write(pipe, b'refresh\n')
        return None

    def _calculate_rate_limit_backoff(self, error: RateLimitError) -> int:
        """Calculate backoff time for rate limit errors.

        For primary rate limits: Use the timing from the error
        For secondary rate limits: Use exponential backoff

        Per GitHub docs:
        - If retry-after present: use it
        - If x-ratelimit-reset present: use it
        - Otherwise: wait 1 min, then exponentially increase

        Args:
            error: RateLimitError with timing information.

        Returns:
            Number of seconds to wait before retrying.

        Raises:
            RateLimitError: If max retries (5) exceeded for secondary rate limits.
        """
        # Primary rate limits: Use exact timing from headers
        if not error.is_secondary:
            if error.retry_after:
                return error.retry_after
            if error.reset_time:
                return max(1, error.reset_time - int(time.time()))
            # Shouldn't happen for primary, but fallback to 60s
            return 60

        # Secondary rate limits: Exponential backoff
        self.consecutive_rate_limit_errors += 1

        # If we have timing info from headers, use it for first attempt
        if self.consecutive_rate_limit_errors == 1:
            if error.retry_after:
                self.log.info(
                    'Secondary rate limit (attempt 1), using retry-after: %ds',
                    error.retry_after,
                )
                return error.retry_after
            # GitHub says "wait at least one minute"
            self.log.info('Secondary rate limit (attempt 1), waiting 60s')
            return 60

        # Subsequent attempts: Exponential backoff
        # 60s, 120s, 240s, 480s, max 600s (10 min)
        backoff = min(60 * (2 ** (self.consecutive_rate_limit_errors - 1)), 600)

        self.log.info(
            'Secondary rate limit (attempt %d), exponential backoff: %ds',
            self.consecutive_rate_limit_errors,
            backoff,
        )

        # Give up after 5 attempts
        if self.consecutive_rate_limit_errors >= 5:
            self.log.error('Hit secondary rate limit 5 times, giving up on task')
            # Reset counter and raise to fail the task
            self.consecutive_rate_limit_errors = 0
            raise error

        return backoff

    def syncSubscribedRepositories(self) -> None:
        """Sync all subscribed repositories and wait for completion."""
        task = SyncSubscribedRepositoriesTask(priority=LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def pruneDatabase(self) -> None:
        """Prune old data from the database and wait for completion."""
        task = PruneDatabaseTask(self.app.config.expire_age, priority=LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def syncOutdatedPullRequests(self) -> None:
        """Sync all outdated pull requests and wait for completion."""
        task = SyncOutdatedPullRequestsTask(priority=LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()
