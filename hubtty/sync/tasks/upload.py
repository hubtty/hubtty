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

"""Tasks for uploading local changes to GitHub."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..task import Task
from ..exceptions import OfflineError

if TYPE_CHECKING:
    from ..sync import Sync


@dataclass
class UploadReviewsTask(Task):
    """Check for pending local changes and submit upload tasks."""

    def run(self, sync: 'Sync') -> None:
        """Find and submit tasks for all pending uploads.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        with app.db.getSession() as session:
            for c in session.getPendingLabels():
                sync.submitTask(SetLabelsTask(c.key, priority=self.priority))
            for c in session.getPendingRebases():
                sync.submitTask(RebasePullRequestTask(c.key, priority=self.priority))
            for c in session.getPendingPullRequestEdits():
                sync.submitTask(EditPullRequestTask(c.key, priority=self.priority))
            for c in session.getPendingMerges():
                sync.submitTask(SendMergeTask(c.key, priority=self.priority))
            for m in session.getPendingMessages():
                sync.submitTask(UploadReviewTask(m.key, priority=self.priority))


@dataclass
class SetLabelsTask(Task):
    """Set labels on a pull request."""

    pr_key: int

    def run(self, sync: 'Sync') -> None:
        """Upload local labels to GitHub.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app

        # Set labels using local ones as source of truth
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            local_labels = [label.name for label in pr.labels]

            data = dict(labels=local_labels)
            pr.pending_labels = False
            # Inside db session for rollback
            sync.put(
                f'repos/{pr.pr_id}/labels'.replace('/pulls/', '/issues/'),
                data
            )
            sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))


@dataclass
class RebasePullRequestTask(Task):
    """Rebase a pull request."""

    pr_key: int

    def run(self, sync: 'Sync') -> None:
        """Request GitHub to rebase the PR branch.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app

        def checkResponse(response):
            self.log.debug('HTTP status code: %d', response.status_code)
            if response.status_code == 503:
                raise OfflineError("Received 503 status code")
            elif response.status_code == 422:
                error_msg = (
                    f'Failed to rebase pull request {pr.pr_id}: '
                    f'{response.json()["message"]}'
                )
                app.error(error_msg)
                self.log.error(error_msg)
            elif response.status_code >= 400:
                raise Exception(
                    f"Received {response.status_code} status code: {response.text}"
                )

        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.pending_rebase = False
            latest_commit = pr.commits[-1]
            if latest_commit:
                headers = {'Accept': 'application/vnd.github.lydian-preview+json'}
                # Inside db session for rollback
                sync.put(
                    f'repos/{pr.pr_id}/update-branch',
                    {'expected_head_sha': latest_commit.sha},
                    headers=headers,
                    response_callback=checkResponse
                )
                sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))


@dataclass
class EditPullRequestTask(Task):
    """Edit a pull request's title, body, or state."""

    pr_key: int

    def run(self, sync: 'Sync') -> None:
        """Upload PR edits to GitHub.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr.pending_edit_message:
                sync.post(
                    f'repos/{pr.pr_id}/comments'.replace('/pulls/', '/issues/'),
                    {'body': pr.pending_edit_message}
                )

            pr.pending_edit = False
            pr.pending_edit_message = None
            edit_params = {
                'title': pr.title,
                'body': pr.body
            }
            if pr.state == 'closed':
                edit_params['state'] = 'close'
            elif pr.state == 'open':
                edit_params['state'] = 'open'
            # Inside db session for rollback
            sync.patch(f'repos/{pr.pr_id}', edit_params)
            sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))


@dataclass
class UploadReviewTask(Task):
    """Upload a review with comments and approval status."""

    message_key: int

    def run(self, sync: 'Sync') -> None:
        """Upload a review to GitHub.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app

        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            if message is None:
                self.log.debug(
                    "Message %s has already been uploaded",
                    self.message_key
                )
                return
            pr = message.commit.pull_request

        if not pr.held:
            self.log.debug("Syncing %s to find out if it should be held", pr.pr_id)
            t = SyncPullRequestTask(pr.pr_id)
            t.run(sync)
            self.results += t.results

        pr_id = None
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            pr = message.commit.pull_request
            if pr.held:
                self.log.debug(
                    "Not uploading review to %s because it is held",
                    pr.pr_id
                )
                return
            pr_id = pr.pr_id

            # Create one review per commit that has comments. Not ideal but
            # better than nothing. I wished it was possible to post only one
            # review.
            # However, github UI allows to post comments to different commits
            # in the same review so it might be possible somehow.
            last_commit = message.commit
            event = "COMMENT"
            for approval in pr.draft_approvals:
                event = approval.state
                session.delete(approval)

            for commit in pr.commits:
                data = dict(commit_id=commit.sha, body='', event=event)
                if commit == last_commit:
                    data['body'] = message.message
                comments = []
                for file in commit.files:
                    if file.draft_comments:
                        for comment in file.draft_comments:
                            # TODO(mandre) add ability to reply to a comment
                            d = dict(
                                path=file.path,
                                line=comment.line,
                                body=comment.message
                            )
                            if comment.parent:
                                d['side'] = 'LEFT'
                            comments.append(d)
                            session.delete(comment)
                if comments:
                    data['comments'] = comments
                if comments or commit == last_commit:
                    # GitHub requires a non-empty body for COMMENT and
                    # REQUEST_CHANGES events.  Skip posting when the
                    # review carries no body text and no inline
                    # comments -- it would be a no-op that the API
                    # rejects with 422.
                    if (not (data.get('body') or '').strip()
                            and not comments
                            and event in ('COMMENT', 'REQUEST_CHANGES')):
                        self.log.debug(
                            "Skipping empty %s review for %s",
                            event, pr_id)
                        if commit == last_commit:
                            break
                        continue
                    # Inside db session for rollback
                    sync.post(f'repos/{pr_id}/reviews', data)
                if commit == last_commit:
                    break

            session.delete(message)
        sync.submitTask(SyncPullRequestTask(pr_id, priority=self.priority))


@dataclass
class SendMergeTask(Task):
    """Merge a pull request."""

    pending_merge_key: int

    def run(self, sync: 'Sync') -> None:
        """Request GitHub to merge the PR.

        Args:
            sync: The Sync instance to use for API calls.
        """
        # Import here to avoid circular imports
        from .pull_request import SyncPullRequestTask

        app = sync.app
        pr_id = None
        with app.db.getSession() as session:
            pm = session.getPendingMerge(self.pending_merge_key)
            data = dict(sha=pm.sha, merge_method=pm.merge_method)
            if pm.commit_title:
                data['commit_title'] = pm.commit_title
            if pm.commit_message:
                data['commit_message'] = pm.commit_message
            pr_id = pm.pull_request.pr_id
            session.delete(pm)
            # Inside db session for rollback
            sync.put(f'repos/{pr_id}/merge', data)

        sync.submitTask(SyncPullRequestTask(pr_id, priority=self.priority))
