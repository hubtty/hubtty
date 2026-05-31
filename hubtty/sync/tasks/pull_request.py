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

"""Pull request synchronization tasks."""

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, TYPE_CHECKING

import dateutil.parser

from hubtty import gitrepo
from ..task import Task
from ..events import RepositoryAddedEvent, PullRequestAddedEvent, PullRequestUpdatedEvent

if TYPE_CHECKING:
    from ..sync import Sync


@dataclass
class SyncOutdatedPullRequestsTask(Task):
    """Sync all pull requests marked as outdated."""

    def run(self, sync: 'Sync') -> None:
        """Submit sync tasks for all outdated PRs.

        Args:
            sync: The Sync instance to use for API calls.
        """
        with sync.app.db.getSession() as session:
            for pr in session.getOutdated():
                self.log.debug("Sync outdated pull request %s", pr.pr_id)
                sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))


@dataclass
class SyncPullRequestTask(Task):
    """Sync a specific pull request from GitHub."""

    pr_id: str
    force_fetch: bool = False

    def _checkResultFromCheck(self, remote_check: Dict[str, Any]) -> Dict[str, Any]:
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

    def _checkResultFromStatus(self, remote_check: Dict[str, Any]) -> Dict[str, Any]:
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

    def _updateChecks(
        self, session, commit, remote_checks_data: List[Dict[str, Any]]
    ) -> None:
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
                self.log.info("Deleted check %s", check.key)
                session.delete(check)

        local_checks = {c.name: c for c in commit.checks}
        for check_data in remote_checks_data:
            check = local_checks.get(check_data['name'])
            if check is None:
                created = dateutil.parser.parse(check_data['created'])
                self.log.info(
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

    def run(self, sync: 'Sync') -> None:
        """Sync the pull request from GitHub.

        Args:
            sync: The Sync instance to use for API calls.
        """
        start_time = time.time()
        try:
            self._syncPullRequest(sync)
            end_time = time.time()
            total_time = end_time - start_time
            self.log.info(
                "Synced pull request %s in %0.5f seconds.",
                self.pr_id, total_time
            )
        except Exception:
            try:
                self.log.error("Marking pull request %s outdated", self.pr_id)
                with sync.app.db.getSession() as session:
                    pr = session.getPullRequestByPullRequestID(self.pr_id)
                    if pr:
                        pr.outdated = True
            except Exception:
                self.log.exception(
                    "Error while marking pull request %s as outdated",
                    self.pr_id
                )
            raise

    def _syncPullRequest(self, sync: 'Sync') -> None:
        """Internal method to sync the pull request.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .repository import SyncRepositoryBranchesTask, SyncRepositoryLabelsTask

        app = sync.app
        remote_pr = sync.get(f'repos/{self.pr_id}')
        remote_commits = sync.get(f'repos/{self.pr_id}/commits?per_page=100',
                                   use_etag=True)
        # Limit to 50, as github seems to struggle sending more comments
        # https://github.com/hubtty/hubtty/issues/59
        remote_pr_comments = sync.get(f'repos/{self.pr_id}/comments?per_page=50',
                                      use_etag=True)
        remote_pr_reviews = sync.get(f'repos/{self.pr_id}/reviews?per_page=100',
                                     use_etag=True)
        remote_issue_comments = sync.get(
            f'repos/{self.pr_id}/comments?per_page=100'.replace('/pulls/', '/issues/'),
            use_etag=True,
        )

        repository_name = remote_pr['base']['repo']['full_name']

        # Get commit details
        for commit in remote_commits:
            remote_commit_details = sync.get(
                f'repos/{repository_name}/commits/{commit["sha"]}',
                use_etag=True,
            )
            commit['_hubtty_remote_commit_details'] = remote_commit_details

        # PR might have been rebased and no longer contain commits
        if len(remote_commits) > 0:
            last_commit = remote_commits[-1]
            last_commit['_hubtty_checks'] = []
            remote_commit_status = sync.get(
                f'repos/{repository_name}/commits/{last_commit["sha"]}/status'
            )
            for check in remote_commit_status['statuses']:
                last_commit['_hubtty_checks'].append(
                    self._checkResultFromStatus(check)
                )
            remote_commit_check_runs = sync.get(
                f'repos/{repository_name}/commits/{last_commit["sha"]}/check-runs'
            )
            for check in remote_commit_check_runs['check_runs']:
                last_commit['_hubtty_checks'].append(
                    self._checkResultFromCheck(check)
                )

        fetches = defaultdict(list)
        with app.db.getSession() as session:
            pr = session.getPullRequestByPullRequestID(self.pr_id)
            if (remote_pr.get('user') or {}).get('id'):
                account = session.getAccountByID(
                    remote_pr['user']['id'],
                    username=remote_pr['user'].get('login')
                )
            else:
                account = session.getSystemAccount()

            if not pr:
                repository = session.getRepositoryByName(repository_name)
                if not repository:
                    self.log.debug(
                        "Repository %s unknown while syncing pull request",
                        repository_name
                    )
                    remote_repository = sync.get(f'repos/{repository_name}')
                    if remote_repository:
                        repository = session.createRepository(
                            remote_repository['full_name'],
                            description=remote_repository.get('description', '')
                        )
                        self.log.info("Created repository %s", repository.name)
                        self.results.append(RepositoryAddedEvent(repository.key))
                        sync.submitTask(
                            SyncRepositoryBranchesTask(
                                repository.name, priority=self.priority
                            )
                        )
                        sync.submitTask(
                            SyncRepositoryLabelsTask(
                                repository.name, priority=self.priority
                            )
                        )
                created = dateutil.parser.parse(remote_pr['created_at'])
                updated = dateutil.parser.parse(remote_pr['updated_at'])
                pr = repository.createPullRequest(
                    remote_pr['id'], account,
                    remote_pr['number'],
                    remote_pr['base']['ref'],
                    self.pr_id,
                    remote_pr['title'],
                    (remote_pr.get('body', '') or '').replace('\r', ''),
                    created, updated,
                    remote_pr['state'],
                    remote_pr['additions'],
                    remote_pr['deletions'],
                    remote_pr['html_url'],
                    remote_pr['merged'],
                    (remote_pr['mergeable'] or False),
                    remote_pr['draft'],
                )
                self.log.info(
                    "Created new pull request %s in local DB.",
                    pr.pr_id
                )
                result = PullRequestAddedEvent(pr.repository.key, pr.key)
            else:
                result = PullRequestUpdatedEvent(pr.repository.key, pr.key)
            app.repository_cache.clear(pr.repository)
            self.results.append(result)
            pr.author = account
            if pr.state != remote_pr['state']:
                pr.state = remote_pr['state']
                result.state_changed = True
            pr.title = remote_pr['title']
            pr.body = (remote_pr.get('body', '') or '').replace('\r', '')
            pr.updated = dateutil.parser.parse(remote_pr['updated_at'])
            pr.additions = remote_pr['additions']
            pr.deletions = remote_pr['deletions']
            pr.merged = remote_pr['merged']
            pr.mergeable = remote_pr.get('mergeable') or False
            pr.draft = remote_pr['draft']

            for label in remote_pr['labels']:
                l = session.getLabel(label['id'])
                if l and l not in pr.labels:
                    pr.addLabel(l)
            remote_label_ids = [label['id'] for label in remote_pr['labels']]
            for label in pr.labels:
                if label.id not in remote_label_ids:
                    pr.removeLabel(label)

            repo = gitrepo.get_repo(pr.repository.name, app.config)
            for remote_commit in remote_commits:
                commit = pr.getCommitBySha(remote_commit['sha'])
                # TODO: handle multiple parents
                url = sync.app.config.git_url + pr.repository.name
                ref = f"pull/{pr.number}/head"
                if (not commit) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not commit:
                    if remote_commit['parents']:
                        parent_sha = remote_commit['parents'][0]['sha']
                    else:
                        parent_sha = None

                    commit = pr.createCommit(
                        (remote_commit['commit']['message'] or '').replace('\r', ''),
                        remote_commit['sha'],
                        parent_sha
                    )
                    self.log.info(
                        "Created new commit %s for pull request %s in local DB.",
                        commit.key, self.pr_id
                    )

                remote_commit_details = remote_commit.get(
                    '_hubtty_remote_commit_details', {}
                )
                for file in remote_commit_details.get('files', []):
                    f = commit.getFile(file['filename'])
                    if f is None:
                        if file.get('patch') is None:
                            inserted = deleted = None
                        else:
                            inserted = file.get('additions', 0)
                            deleted = file.get('deletions', 0)
                        f = commit.createFile(
                            file['filename'], file['status'],
                            file.get('previous_filename'),
                            inserted, deleted
                        )

                # Commit checks
                if remote_commit.get('_hubtty_checks'):
                    self._updateChecks(
                        session, commit, remote_commit['_hubtty_checks']
                    )

            # Commit reviews
            remote_pr_reviews.extend(remote_issue_comments)
            for remote_review in remote_pr_reviews:

                # TODO(mandre) sync pending reviews
                if remote_review.get('state') == 'PENDING':
                    continue

                self.log.info("New review comment %s", remote_review)
                if (remote_review.get('user') or {}).get('id'):
                    account = session.getAccountByID(
                        remote_review['user']['id'],
                        username=remote_review['user'].get('login')
                    )
                else:
                    account = session.getSystemAccount()

                associated_commit_id = None
                if remote_review.get('commit_id'):
                    associated_commit = pr.getCommitBySha(remote_review['commit_id'])
                    if associated_commit:
                        associated_commit_id = associated_commit.key

                message = session.getMessageByID(remote_review['id'])
                if not message:
                    # Normalize date -> created
                    creation_date = remote_review.get(
                        'submitted_at', remote_review.get('created_at')
                    )
                    if creation_date:
                        created = dateutil.parser.parse(creation_date)
                    message = pr.createMessage(
                        associated_commit_id, remote_review['id'], account, created,
                        (remote_review.get('body', '') or '').replace('\r', '')
                    )
                    self.log.info(
                        "Created new review message %s for pull request %s in local DB.",
                        message.key, pr.pr_id
                    )
                else:
                    if message.author != account:
                        message.author = account
                    message.body = (remote_review.get('body', '') or '').replace('\r', '')

                review_state = remote_review.get('state')
                if review_state and remote_review.get('commit_id'):
                    approval = session.getApproval(
                        pr, account, remote_review.get('commit_id')
                    )
                    own_approval = session.getApproval(
                        pr, session.getOwnAccount(), remote_review.get('commit_id')
                    )

                    # Someone left a negative vote after the local
                    # user created a draft positive vote.  Hold the
                    # change so that it doesn't look like the local
                    # user is ignoring negative feedback.
                    if (own_approval
                            and own_approval != approval
                            and own_approval.draft
                            and own_approval.state not in [
                                "CHANGES_REQUESTED", "REQUEST_CHANGES"
                            ]
                            and review_state == "CHANGES_REQUESTED"
                            and not (approval and approval.state == "CHANGES_REQUESTED")
                            and not pr.held):
                        pr.held = True
                        result.held_changed = True
                        self.log.info(
                            "Setting pull request %s to held due to negative "
                            "review after positive",
                            pr.pr_id
                        )

                    if approval:
                        # Only update approval if it hasn't been changed locally
                        if not approval.draft:
                            approval.state = review_state
                    else:
                        pr.createApproval(
                            account, review_state, remote_review.get('commit_id')
                        )
                        self.log.info(
                            "Created new approval for %s from %s commit %s.",
                            pr.pr_id, account.username, remote_review.get('commit_id')
                        )

            # Inline comments
            for remote_comment in remote_pr_comments:
                if (remote_comment.get('user') or {}).get('id'):
                    account = session.getAccountByID(
                        remote_comment['user']['id'],
                        username=remote_comment['user'].get('login')
                    )
                else:
                    account = session.getSystemAccount()
                comment = session.getCommentByID(remote_comment['id'])

                file_id = None
                associated_commit = pr.getCommitBySha(remote_comment['commit_id'])
                if associated_commit:
                    fileobj = associated_commit.getFile(remote_comment['path'])
                    if fileobj is None:
                        fileobj = associated_commit.createFile(
                            remote_comment['path'], 'modified'
                        )
                    file_id = fileobj.key

                updated = dateutil.parser.parse(remote_comment['updated_at'])
                if not comment:
                    created = dateutil.parser.parse(remote_comment['created_at'])
                    parent = False
                    if remote_comment.get('side', '') == 'LEFT':
                        parent = True
                    message = session.getMessageByID(
                        remote_comment['pull_request_review_id']
                    )

                    comment = message.createComment(
                        file_id, remote_comment['id'], account,
                        remote_comment.get('in_reply_to_id'),
                        created, updated, parent,
                        remote_comment.get('commit_id'),
                        remote_comment.get('original_commit_id'),
                        remote_comment.get('line'),
                        remote_comment.get('original_line'),
                        (remote_comment.get('body', '') or '').replace('\r', ''),
                        url=remote_comment.get('html_url')
                    )
                    self.log.info(
                        "Created new comment %s for pull request %s in local DB.",
                        comment.key, pr.pr_id
                    )
                else:
                    if comment.author != account:
                        comment.author = account
                    if comment.updated != updated:
                        comment.updated = updated
                    if comment.commit_id != remote_comment.get('commit_id'):
                        comment.commit_id = remote_comment.get('commit_id')
                    if comment.line != remote_comment.get('line'):
                        comment.line = remote_comment.get('line')
                    if comment.file_key != file_id:
                        comment.file_key = file_id
                    comment.body = (
                        remote_comment.get('body', '') or ''
                    ).replace('\r', '')

            # Delete commits that no longer belong to the pull request
            # Do it at the end so that we don't inadvertently delete
            # associated comments or message in the session
            remote_commits_sha = [c['sha'] for c in remote_commits]
            for commit in pr.commits:
                if commit.sha not in remote_commits_sha:
                    session.delete(commit)

            pr.outdated = False
        for url, refs in fetches.items():
            self.log.debug("Fetching from %s with refs %s", url, refs)
            repo.fetch(url, refs)
