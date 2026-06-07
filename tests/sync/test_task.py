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

"""Tests for task equality — non-identity fields excluded from comparison."""

from hubtty.sync.tasks.pull_request import (
    SyncPullRequestTask,
    SyncPullRequestChecksTask,
)
from hubtty.sync.tasks.repository_check import CheckCommitsTask


class TestTaskEquality:
    """Non-identity fields (compare=False) must not affect equality."""

    def test_sync_pr_checks_task_equal_ignores_attempt(self):
        """SyncPullRequestChecksTask with different attempt values are equal."""
        t1 = SyncPullRequestChecksTask(
            pr_id='owner/repo/pulls/1', repository_name='owner/repo', attempt=0
        )
        t2 = SyncPullRequestChecksTask(
            pr_id='owner/repo/pulls/1', repository_name='owner/repo', attempt=12
        )
        assert t1 == t2

    def test_sync_pr_checks_task_different_pr_not_equal(self):
        """SyncPullRequestChecksTask with different pr_id are not equal."""
        t1 = SyncPullRequestChecksTask(
            pr_id='owner/repo/pulls/1', repository_name='owner/repo', attempt=0
        )
        t2 = SyncPullRequestChecksTask(
            pr_id='owner/repo/pulls/2', repository_name='owner/repo', attempt=0
        )
        assert t1 != t2

    def test_sync_pr_task_equal_ignores_force_fetch(self):
        """SyncPullRequestTask with different force_fetch values are equal."""
        t1 = SyncPullRequestTask(pr_id='owner/repo/pulls/1', force_fetch=False)
        t2 = SyncPullRequestTask(pr_id='owner/repo/pulls/1', force_fetch=True)
        assert t1 == t2

    def test_sync_pr_task_different_pr_not_equal(self):
        """SyncPullRequestTask with different pr_id are not equal."""
        t1 = SyncPullRequestTask(pr_id='owner/repo/pulls/1')
        t2 = SyncPullRequestTask(pr_id='owner/repo/pulls/2')
        assert t1 != t2

    def test_check_commits_task_equal_ignores_force_fetch(self):
        """CheckCommitsTask with different force_fetch values are equal."""
        t1 = CheckCommitsTask(repository_key=42, force_fetch=False)
        t2 = CheckCommitsTask(repository_key=42, force_fetch=True)
        assert t1 == t2

    def test_check_commits_task_different_key_not_equal(self):
        """CheckCommitsTask with different repository_key are not equal."""
        t1 = CheckCommitsTask(repository_key=42)
        t2 = CheckCommitsTask(repository_key=99)
        assert t1 != t2
