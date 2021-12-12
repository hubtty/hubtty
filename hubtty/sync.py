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

import collections
import errno
import logging
import os
import threading
import json
import time
import datetime
import re

import dateutil.parser
try:
    import ordereddict
except:
    pass
import requests
import requests.utils
import six
from six.moves import queue

import hubtty.version
from hubtty import gitrepo

HIGH_PRIORITY=0
NORMAL_PRIORITY=1
LOW_PRIORITY=2

TIMEOUT=30

class OfflineError(Exception):
    pass

class RestrictedError(Exception):
    pass

class RateLimitError(Exception):
    pass

class MultiQueue(object):
    def __init__(self, priorities):
        try:
            self.queues = collections.OrderedDict()
        except AttributeError:
            self.queues = ordereddict.OrderedDict()
        for key in priorities:
            self.queues[key] = collections.deque()
        self.condition = threading.Condition()
        self.incomplete = []

    def qsize(self):
        count = 0
        self.condition.acquire()
        try:
            for q in self.queues.values():
                count += len(q)
            return count + len(self.incomplete)
        finally:
            self.condition.release()

    def put(self, item, priority):
        added = False
        self.condition.acquire()
        try:
            if item not in self.queues[priority]:
                self.queues[priority].append(item)
                added = True
            self.condition.notify()
        finally:
            self.condition.release()
        return added

    def get(self):
        self.condition.acquire()
        try:
            while True:
                for q in self.queues.values():
                    try:
                        ret = q.popleft()
                        self.incomplete.append(ret)
                        return ret
                    except IndexError:
                        pass
                self.condition.wait()
        finally:
            self.condition.release()

    def find(self, klass, priority):
        results = []
        self.condition.acquire()
        try:
            for item in self.queues[priority]:
                if isinstance(item, klass):
                    results.append(item)
        finally:
            self.condition.release()
        return results

    def complete(self, item):
        self.condition.acquire()
        try:
            if item in self.incomplete:
                self.incomplete.remove(item)
        finally:
            self.condition.release()


class UpdateEvent(object):
    def updateRelatedPullRequests(self, session, pr):
        related_pr_keys = set()
        related_pr_keys.add(pr.key)
        for commit in pr.commits:
            parent = pr.getCommitBySha(commit.parent)
            if parent:
                related_pr_keys.add(parent.pull_request.key)
            for child in session.getCommitsByParent(commit.commit):
                related_pr_keys.add(child.pull_request.key)
        self.related_pr_keys = related_pr_keys

class RepositoryAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<RepositoryAddedEvent repository_key:%s>' % (
            self.repository_key,)

    def __init__(self, repository):
        self.repository_key = repository.key

class PullRequestAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<PullRequestAddedEvent repository_key:%s pr_key:%s>' % (
            self.repository_key, self.pr_key)

    def __init__(self, pr):
        self.repository_key = pr.repository.key
        self.pr_key = pr.key
        self.related_pr_keys = set()
        self.review_flag_changed = True
        self.state_changed = True
        self.held_changed = False

class PullRequestUpdatedEvent(UpdateEvent):
    def __repr__(self):
        return '<PullRequestUpdatedEvent repository_key:%s pr_key:%s review_flag_changed:%s state_changed:%s>' % (
            self.repository_key, self.pr_key, self.review_flag_changed, self.state_changed)

    def __init__(self, pr):
        self.repository_key = pr.repository.key
        self.pr_key = pr.key
        self.related_pr_keys = set()
        self.review_flag_changed = False
        self.state_changed = False
        self.held_changed = False

class Task(object):
    def __init__(self, priority=NORMAL_PRIORITY):
        self.log = logging.getLogger('hubtty.sync')
        self.priority = priority
        self.succeeded = None
        self.event = threading.Event()
        self.tasks = []
        self.results = []

    def complete(self, success):
        self.succeeded = success
        self.event.set()

    def wait(self, timeout=None):
        self.event.wait(timeout)
        return self.succeeded

    def __eq__(self, other):
        raise NotImplementedError()

class SyncOwnAccountTask(Task):
    def __repr__(self):
        return '<SyncOwnAccountTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('user')
        sync.account_id = remote['id']
        with app.db.getSession() as session:
            account = session.getAccountByID(remote['id'],
                                             remote.get('name'),
                                             remote.get('login'),
                                             remote.get('email'))
            session.setOwnAccount(account)
        app.own_account_id = remote['id']

class SyncAccountTask(Task):
    def __init__(self, username, priority=NORMAL_PRIORITY):
        super(SyncAccountTask, self).__init__(priority)
        self.username = username

    def __repr__(self):
        return '<SyncAccountTask %s>' % (self.username,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.username == self.username):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('users/' + self.username)
        with app.db.getSession() as session:
            session.getAccountByID(remote['id'],
                                   remote.get('name'),
                                   remote.get('login'),
                                   remote.get('email'))

class SyncRepositoryListTask(Task):
    def __repr__(self):
        return '<SyncRepositoryListTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app

        remote_repos = sync.get('user/repos?per_page=100')
        remote_repos_names = [r['full_name'] for r in remote_repos]

        def checkResponse(response):
            self.log.debug('HTTP status code: %d', response.status_code)
            if response.status_code == 503:
                raise OfflineError("Received 503 status code")
            elif response.status_code == 404:
                self.log.error('Repository %s does not exist or you do not have '
                        'the permissions to view it.' % additional_repo)
            elif response.status_code >= 400:
                raise Exception("Received %s status code: %s"
                                % (response.status_code, response.text))

        # Add additional repos
        for additional_repo in sync.app.config.additional_repositories:
            if additional_repo not in remote_repos_names:
                remote_repo = sync.get('repos/%s' % additional_repo,
                        response_callback=checkResponse)
                if remote_repo:
                    remote_repos.append(remote_repo)
                    remote_repos_names.append(additional_repo)

        with app.db.getSession() as session:
            for remote_repo in remote_repos:
                repo_name = remote_repo['full_name']
                repo_desc = (remote_repo.get('description', '') or '').replace('\r','')
                repository = session.getRepositoryByName(repo_name)
                if not repository:
                    repository = session.createRepository(repo_name,
                                                    description=repo_desc)
                    self.log.info("Created repository %s", repo_name)
                    self.results.append(RepositoryAddedEvent(repository))
                repository.description = repo_desc
                repository.can_push = remote_repo['permissions']['push']

            for p in session.getRepositories():
                if p.name not in remote_repos_names:
                    self.log.info("Deleted repository %s", p.name)
                    session.delete(p)

class SyncSubscribedRepositoryBranchesTask(Task):
    def __repr__(self):
        return '<SyncSubscribedRepositoryBranchesTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            repositories = session.getRepositories(subscribed=True)
        for p in repositories:
            sync.submitTask(SyncRepositoryBranchesTask(p.name, self.priority))

class SyncRepositoryBranchesTask(Task):
    def __init__(self, repository_name, priority=NORMAL_PRIORITY):
        super(SyncRepositoryBranchesTask, self).__init__(priority)
        self.repository_name = repository_name

    def __repr__(self):
        return '<SyncRepositoryBranchesTask %s>' % (self.repository_name,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.repository_name == self.repository_name):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('repos/%s/branches?per_page=100' % self.repository_name)
        remote_branches = set()
        for b in remote:
            remote_branches.add(b['name'])
        with app.db.getSession() as session:
            local = {}
            repository = session.getRepositoryByName(self.repository_name)
            for branch in repository.branches:
                local[branch.name] = branch
            local_branches = set(local.keys())

            for name in local_branches-remote_branches:
                session.delete(local[name])
                self.log.info("Deleted branch %s from repository %s in local DB.", name, repository.name)

            for name in remote_branches-local_branches:
                repository.createBranch(name)
                self.log.info("Added branch %s to repository %s in local DB.", name, repository.name)

class SyncSubscribedRepositoryLabelsTask(Task):
    def __repr__(self):
        return '<SyncSubscribedRepositoryLabelsTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            repositories = session.getRepositories(subscribed=True)
        for p in repositories:
            sync.submitTask(SyncRepositoryLabelsTask(p.name, self.priority))

class SyncRepositoryLabelsTask(Task):
    def __init__(self, repository_name, priority=NORMAL_PRIORITY):
        super(SyncRepositoryLabelsTask, self).__init__(priority)
        self.repository_name = repository_name

    def __repr__(self):
        return '<SyncRepositoryLabelsTask %s>' % (self.repository_name,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.repository_name == self.repository_name):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote_labels = sync.get('repos/%s/labels' % (self.repository_name,))
        with app.db.getSession() as session:
            repository = session.getRepositoryByName(self.repository_name)

            for remote_label in remote_labels:
                label = session.getLabel(remote_label['id'])
                if not label:
                    self.log.info("Created label %s for repository %s", remote_label['name'], repository.name)
                    repository.createLabel(remote_label['id'], remote_label['name'],
                            remote_label['color'], remote_label['description'])
                else:
                    label.name = remote_label['name']
                    label.color = remote_label['color']
                    label.description = remote_label['description']

            # Delete old labels
            remote_label_ids = [l['id'] for l in remote_labels]
            for l in repository.labels:
                if l.id not in remote_label_ids:
                    self.log.info("Deleted label %s", l.name)
                    session.delete(l)

class SyncSubscribedRepositoriesTask(Task):
    def __repr__(self):
        return '<SyncSubscribedRepositoriesTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            keys = [p.key for p in session.getRepositories(subscribed=True)]
        # Sync repositories at most 10 at a time
        for i in range(0, len(keys), 10):
            t = SyncRepositoryTask(keys[i:i+10], self.priority)
            self.tasks.append(t)
            sync.submitTask(t)

class SyncRepositoryTask(Task):
    def __init__(self, repository_keys, priority=NORMAL_PRIORITY):
        super(SyncRepositoryTask, self).__init__(priority)
        if type(repository_keys) == int:
            repository_keys = [repository_keys]
        self.repository_keys = repository_keys

    def __repr__(self):
        return '<SyncRepositoryTask %s>' % (self.repository_keys,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.repository_keys == self.repository_keys):
            return True
        return False

    def run(self, sync):
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
            for repository_name in repositories:
                query += ' repo:%s' % repository_name
            pull_requests = sync.query(query)
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
            query = 'type:pr updated:>%s' % ((sync_from - datetime.timedelta(seconds=4)).replace(microsecond=0).isoformat(),)
            sync_repositories(partial_sync, query)

        for key in self.repository_keys:
            sync.submitTask(SetRepositoryUpdatedTask(key, now, priority=self.priority))

class SetRepositoryUpdatedTask(Task):
    def __init__(self, repository_key, updated, priority=NORMAL_PRIORITY):
        super(SetRepositoryUpdatedTask, self).__init__(priority)
        self.repository_key = repository_key
        self.updated = updated

    def __repr__(self):
        return '<SetRepositoryUpdatedTask %s %s>' % (self.repository_key, self.updated)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.repository_key == self.repository_key and
            other.updated == self.updated):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            repository = session.getRepository(self.repository_key)
            repository.updated = self.updated

class SyncOutdatedPullRequestsTask(Task):
    def __init__(self, priority=NORMAL_PRIORITY):
        super(SyncOutdatedPullRequestsTask, self).__init__(priority)

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def __repr__(self):
        return '<SyncOutdatedPullRequestsTask>'

    def run(self, sync):
        with sync.app.db.getSession() as session:
            for pr in session.getOutdated():
                self.log.debug("Sync outdated pull request %s" % (pr.pr_id,))
                sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))

class SyncPullRequestTask(Task):
    def __init__(self, pr_id, force_fetch=False, priority=NORMAL_PRIORITY):
        super(SyncPullRequestTask, self).__init__(priority)
        self.pr_id = pr_id
        self.force_fetch = force_fetch

    def __repr__(self):
        return '<SyncPullRequestTask %s>' % (self.pr_id,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.pr_id == self.pr_id and
            other.force_fetch == self.force_fetch):
            return True
        return False

    def _checkResultFromCheck(self, remote_check):
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

    def _checkResultFromStatus(self, remote_check):
        check = {}
        check['name'] = remote_check['context']
        check['url'] = remote_check.get('target_url', '')
        check['state'] = remote_check['state']
        check['message'] = remote_check.get('description', '')

        check['created'] = remote_check['created_at']
        check['updated'] = remote_check['updated_at']

        return check

    def _updateChecks(self, session, commit, remote_checks_data):
        # Called from run inside of db transaction

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
                self.log.info("Creating check %s on commit %s", check_data['name'], commit.key)
                check = commit.createCheck(check_data['name'],
                        check_data['state'], created, created)
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

    def run(self, sync):
        start_time = time.time()
        try:
            self._syncPullRequest(sync)
            end_time = time.time()
            total_time = end_time - start_time
            self.log.info("Synced pull request %s in %0.5f seconds.", self.pr_id, total_time)
        except Exception:
            try:
                self.log.error("Marking pull request %s outdated" % (self.pr_id,))
                with sync.app.db.getSession() as session:
                    pr = session.getPullRequestByPullRequestID(self.pr_id)
                    if pr:
                        pr.outdated = True
            except Exception:
                self.log.exception("Error while marking pull request %s as outdated" % (self.pr_id,))
            raise

    def _syncPullRequest(self, sync):
        app = sync.app
        remote_pr = sync.get('repos/%s' % self.pr_id)
        remote_commits = sync.get('repos/%s/commits?per_page=100' % self.pr_id)
        # Limit to 50, as github seems to struggle sending more comments
        # https://github.com/hubtty/hubtty/issues/59
        remote_pr_comments = sync.get('repos/%s/comments?per_page=50' % self.pr_id)
        remote_pr_reviews = sync.get('repos/%s/reviews?per_page=100' % self.pr_id)
        remote_issue_comments = sync.get(('repos/%s/comments?per_page=100'
                                          % self.pr_id).replace('/pulls/', '/issues/'))

        repository_name = remote_pr['base']['repo']['full_name']

        # Get commit details
        for commit in remote_commits:
            remote_commit_details = sync.get('repos/%s/commits/%s'
                    % (repository_name, commit['sha']))
            commit['_hubtty_remote_commit_details'] = remote_commit_details

        # PR might have been rebased and no longer contain commits
        if len(remote_commits) > 0:
            last_commit = remote_commits[-1]
            last_commit['_hubtty_checks'] = []
            remote_commit_status = sync.get(
                    'repos/%s/commits/%s/status' % (repository_name, last_commit['sha']))
            for check in remote_commit_status['statuses']:
                last_commit['_hubtty_checks'].append(self._checkResultFromStatus(check))
            remote_commit_check_runs = sync.get(
                    'repos/%s/commits/%s/check-runs' % (repository_name, last_commit['sha']))
            for check in remote_commit_check_runs['check_runs']:
                last_commit['_hubtty_checks'].append(self._checkResultFromCheck(check))

        fetches = collections.defaultdict(list)
        with app.db.getSession() as session:
            pr = session.getPullRequestByPullRequestID(self.pr_id)
            if (remote_pr.get('user') or {}).get('id'):
                account = session.getAccountByID(remote_pr['user']['id'],
                                                 username=remote_pr['user'].get('login'))
            else:
                account = session.getSystemAccount()

            if not pr:
                repository = session.getRepositoryByName(repository_name)
                if not repository:
                    self.log.debug("Repository %s unknown while syncing pull request" % (repository_name,))
                    remote_repository = sync.get('repos/%s' % (repository_name,))
                    if remote_repository:
                        repository = session.createRepository(
                            remote_repository['full_name'],
                            description=remote_repository.get('description', ''))
                        self.log.info("Created repository %s", repository.name)
                        self.results.append(RepositoryAddedEvent(repository))
                        sync.submitTask(SyncRepositoryBranchesTask(repository.name, self.priority))
                        sync.submitTask(SyncRepositoryLabelsTask(repository.name, self.priority))
                created = dateutil.parser.parse(remote_pr['created_at'])
                updated = dateutil.parser.parse(remote_pr['updated_at'])
                pr = repository.createPullRequest(remote_pr['id'], account,
                                                  remote_pr['number'],
                                                  remote_pr['base']['ref'],
                                                  self.pr_id,
                                                  remote_pr['title'],
                                                  (remote_pr.get('body','') or '').replace('\r',''),
                                                  created, updated,
                                                  remote_pr['state'],
                                                  remote_pr['additions'],
                                                  remote_pr['deletions'],
                                                  remote_pr['html_url'],
                                                  remote_pr['merged'],
                                                  (remote_pr['mergeable'] or False),
                                                  )
                self.log.info("Created new pull request %s in local DB.", pr.pr_id)
                result = PullRequestAddedEvent(pr)
            else:
                result = PullRequestUpdatedEvent(pr)
            app.repository_cache.clear(pr.repository)
            self.results.append(result)
            pr.author = account
            if pr.state != remote_pr['state']:
                pr.state = remote_pr['state']
                result.state_changed = True
            pr.title = remote_pr['title']
            pr.body = (remote_pr.get('body','') or '').replace('\r','')
            pr.updated = dateutil.parser.parse(remote_pr['updated_at'])
            pr.additions = remote_pr['additions']
            pr.deletions = remote_pr['deletions']
            pr.merged = remote_pr['merged']
            pr.mergeable = remote_pr.get('mergeable') or False

            for label in remote_pr['labels']:
                l = session.getLabel(label['id'])
                if l and l not in pr.labels:
                    pr.addLabel(l)
            remote_label_ids = [l['id'] for l in remote_pr['labels']]
            for label in pr.labels:
                if label.id not in remote_label_ids:
                    pr.removeLabel(label)

            # Delete commits that no longer belong to the pull request
            remote_commits_sha = [c['sha'] for c in remote_commits]
            for commit in pr.commits:
                if commit.sha not in remote_commits_sha:
                    self.log.info("Deleted commit %s", commit.sha)
                    session.delete(commit)

            repo = gitrepo.get_repo(pr.repository.name, app.config)
            for remote_commit in remote_commits:
                commit = pr.getCommitBySha(remote_commit['sha'])
                # TODO: handle multiple parents
                url = sync.app.config.git_url + pr.repository.name
                ref = "pull/%s/head" % (pr.number,)
                if (not commit) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not commit:
                    commit = pr.createCommit((remote_commit['commit']['message'] or '').replace('\r',''),
                                              remote_commit['sha'],
                                              remote_commit['parents'][0]['sha'])
                    self.log.info("Created new commit %s for pull request %s in local DB.",
                                  commit.key, self.pr_id)

                remote_commit_details = remote_commit.get('_hubtty_remote_commit_details', {})
                for file in remote_commit_details['files']:
                    f = commit.getFile(file['filename'])
                    if f is None:
                        if file.get('patch') == None:
                            inserted = deleted = None
                        else:
                            inserted = file.get('additions', 0)
                            deleted = file.get('deletions', 0)
                        f = commit.createFile(file['filename'], file['status'],
                                                file.get('previous_filename'),
                                                inserted, deleted)

                # Commit checks
                if remote_commit.get('_hubtty_checks'):
                    self._updateChecks(session, commit, remote_commit['_hubtty_checks'])

            # Commit reviews
            remote_pr_reviews.extend(remote_issue_comments)
            for remote_review in remote_pr_reviews:

                # TODO(mandre) sync pending reviews
                if remote_review.get('state') == 'PENDING':
                    continue

                self.log.info("New review comment %s", remote_review)
                if (remote_review.get('user') or {}).get('id'):
                    account = session.getAccountByID(remote_review['user']['id'],
                                                     username=remote_review['user'].get('login'))
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
                    creation_date = remote_review.get('submitted_at', remote_review.get('created_at'))
                    if creation_date:
                        created = dateutil.parser.parse(creation_date)
                    message = pr.createMessage(associated_commit_id, remote_review['id'], account, created,
                                                   (remote_review.get('body','') or '').replace('\r',''))
                    self.log.info("Created new review message %s for pull request %s in local DB.", message.key, pr.pr_id)
                else:
                    if message.author != account:
                        message.author = account
                    message.body = (remote_review.get('body','') or '').replace('\r','')

                review_state = remote_review.get('state')
                if review_state:
                    approval = session.getApproval(pr, account, remote_review.get('commit_id'))
                    own_approval = session.getApproval(pr, session.getOwnAccount(), remote_review.get('commit_id'))

                    # Someone left a negative vote after the local
                    # user created a draft positive vote.  Hold the
                    # change so that it doesn't look like the local
                    # user is ignoring negative feedback.
                    if own_approval \
                            and own_approval != approval \
                            and own_approval.draft \
                            and own_approval.state not in ["CHANGES_REQUESTED", "REQUEST_CHANGES"] \
                            and review_state == "CHANGES_REQUESTED" \
                            and not (approval and approval.state == "CHANGES_REQUESTED") \
                            and not pr.held:
                                pr.held = True
                                result.held_changed = True
                                self.log.info("Setting pull request %s to held due to negative review after positive", pr.pr_id)

                    if approval:
                        # Only update approval if it hasn't been changed locally
                        if not approval.draft:
                            approval.state = review_state
                    else:
                        pr.createApproval(account, review_state, remote_review.get('commit_id'))
                        self.log.info("Created new approval for %s from %s commit %s.", pr.pr_id, account.username, remote_review.get('commit_id'))

            # Inline comments
            for remote_comment in remote_pr_comments:
                if (remote_comment.get('user') or {}).get('id'):
                    account = session.getAccountByID(remote_comment['user']['id'],
                                                     username=remote_comment['user'].get('login'))
                else:
                    account = session.getSystemAccount()
                comment = session.getCommentByID(remote_comment['id'])

                file_id = None
                associated_commit = pr.getCommitBySha(remote_comment['commit_id'])
                if associated_commit:
                    fileobj = associated_commit.getFile(remote_comment['path'])
                    if fileobj is None:
                        fileobj = associated_commit.createFile(remote_comment['path'], 'modified')
                    file_id = fileobj.key

                updated = dateutil.parser.parse(remote_comment['updated_at'])
                if not comment:
                    created = dateutil.parser.parse(remote_comment['created_at'])
                    parent = False
                    if remote_comment.get('side', '') == 'LEFT':
                        parent = True
                    message = session.getMessageByID(remote_comment['pull_request_review_id'])

                    comment = message.createComment(file_id, remote_comment['id'], account,
                                                    remote_comment.get('in_reply_to_id'),
                                                    created, updated, parent,
                                                    remote_comment.get('commit_id'),
                                                    remote_comment.get('original_commit_id'),
                                                    remote_comment.get('line'),
                                                    remote_comment.get('original_line'),
                                                    (remote_comment.get('body','') or '').replace('\r',''),
                                                    url = remote_comment.get('html_url'))
                    self.log.info("Created new comment %s for pull request %s in local DB.",
                                    comment.key, pr.pr_id)
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
                    comment.body = (remote_comment.get('body','') or '').replace('\r','')

            pr.outdated = False
        for url, refs in fetches.items():
            self.log.debug("Fetching from %s with refs %s", url, refs)
            try:
                repo.fetch(url, refs)
            except Exception:
                # Backwards compat with GitPython before the multi-ref fetch
                # patch.
                # (https://github.com/gitpython-developers/GitPython/pull/170)
                for ref in refs:
                    self.log.debug("git fetch %s %s" % (url, ref))
                    repo.fetch(url, ref)

class CheckReposTask(Task):
    # on startup, check all repositories
    #   for any subscribed repository without a local repo or if
    #   --fetch-missing-refs is supplied, check all local pull requests for
    #   missing refs, and sync the associated pull requests
    def __repr__(self):
        return '<CheckReposTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
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
                        CheckCommitsTask(repository.key,
                                           force_fetch=app.fetch_missing_refs,
                                           priority=LOW_PRIORITY)
                    )
            except Exception:
                self.log.exception("Exception checking repo %s" %
                                   (repository.name,))

class CheckCommitsTask(Task):
    def __init__(self, repository_key, force_fetch=False,
                 priority=NORMAL_PRIORITY):
        super(CheckCommitsTask, self).__init__(priority)
        self.repository_key = repository_key
        self.force_fetch = force_fetch

    def __repr__(self):
        return '<CheckCommitsTask %s>' % (self.repository_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.repository_key == self.repository_key):
            return True
        return False

    def run(self, sync):
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
                        if repo.checkCommits([commit.parent, commit.sha]):
                            to_sync.add(pr.pr_id)
                else:
                    to_sync.add(pr.pr_id)
        for pr_id in to_sync:
            sync.submitTask(SyncPullRequestTask(pr_id,
                                                force_fetch=self.force_fetch,
                                                priority=self.priority))

class UploadReviewsTask(Task):
    def __repr__(self):
        return '<UploadReviewsTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            for c in session.getPendingLabels():
                sync.submitTask(SetLabelsTask(c.key, self.priority))
            for c in session.getPendingRebases():
                sync.submitTask(RebasePullRequestTask(c.key, self.priority))
            for c in session.getPendingPullRequestEdits():
                sync.submitTask(EditPullRequestTask(c.key, self.priority))
            for c in session.getPendingMerges():
                sync.submitTask(SendMergeTask(c.key, self.priority))
            for m in session.getPendingMessages():
                sync.submitTask(UploadReviewTask(m.key, self.priority))

class SetLabelsTask(Task):
    def __init__(self, pr_key, priority=NORMAL_PRIORITY):
        super(SetLabelsTask, self).__init__(priority)
        self.pr_key = pr_key

    def __repr__(self):
        return '<SetLabelsTask %s>' % (self.pr_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.pr_key == self.pr_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        # Set labels using local ones as source of truth
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            local_labels = [l.name for l in pr.labels]

            data = dict(labels=local_labels)
            pr.pending_labels = False
            # Inside db session for rollback
            sync.put(('repos/%s/labels' % pr.pr_id).replace('/pulls/', '/issues/'),
                    data)
            sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))

class RebasePullRequestTask(Task):
    def __init__(self, pr_key, priority=NORMAL_PRIORITY):
        super(RebasePullRequestTask, self).__init__(priority)
        self.pr_key = pr_key

    def __repr__(self):
        return '<RebasePullRequestTask %s>' % (self.pr_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.pr_key == self.pr_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        def checkResponse(response):
            self.log.debug('HTTP status code: %d', response.status_code)
            if response.status_code == 503:
                raise OfflineError("Received 503 status code")
            elif response.status_code == 422:
                error_msg = 'Failed to rebase pull request %s: %s' % (pr.pr_id, response.json()['message'])
                app.error(error_msg)
                self.log.error(error_msg)
            elif response.status_code >= 400:
                raise Exception("Received %s status code: %s"
                                % (response.status_code, response.text))

        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            pr.pending_rebase = False
            latest_commit = pr.commits[-1]
            if latest_commit:
                headers = {'Accept': 'application/vnd.github.lydian-preview+json'}
                # Inside db session for rollback
                sync.put('repos/%s/update-branch' % (pr.pr_id,), {
                    'expected_head_sha': latest_commit.sha,
                    }, headers=headers, response_callback=checkResponse)
                sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))

class EditPullRequestTask(Task):
    def __init__(self, pr_key, priority=NORMAL_PRIORITY):
        super(EditPullRequestTask, self).__init__(priority)
        self.pr_key = pr_key

    def __repr__(self):
        return '<EditPullRequestTask %s>' % (self.pr_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.pr_key == self.pr_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            if pr.pending_edit_message:
                sync.post(('repos/%s/comments' % pr.pr_id).replace('/pulls/', '/issues/'),
                        {'body': pr.pending_edit_message})

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
            sync.patch('repos/%s' % (pr.pr_id,), edit_params)
            sync.submitTask(SyncPullRequestTask(pr.pr_id, priority=self.priority))

class UploadReviewTask(Task):
    def __init__(self, message_key, priority=NORMAL_PRIORITY):
        super(UploadReviewTask, self).__init__(priority)
        self.message_key = message_key

    def __repr__(self):
        return '<UploadReviewTask %s>' % (self.message_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.message_key == self.message_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            if message is None:
                self.log.debug("Message %s has already been uploaded" % (
                    self.message_key))
                return
            pr = message.commit.pull_request
        if not pr.held:
            self.log.debug("Syncing %s to find out if it should be held" % (pr.pr_id,))
            t = SyncPullRequestTask(pr.pr_id)
            t.run(sync)
            self.results += t.results
        pr_id = None
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            pr = message.commit.pull_request
            if pr.held:
                self.log.debug("Not uploading review to %s because it is held" %
                               (pr.pr_id,))
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
                data = dict(commit_id=commit.sha,
                            body='',
                            event=event)
                if commit == last_commit:
                    data['body'] = message.message
                comments = []
                for file in commit.files:
                    if file.draft_comments:
                        for comment in file.draft_comments:
                            # TODO(mandre) add ability to reply to a comment
                            d = dict(path=file.path,
                                    line=comment.line,
                                    body=comment.message)
                            if comment.parent:
                                d['side'] = 'LEFT'
                            comments.append(d)
                            session.delete(comment)
                if comments:
                    data['comments'] = comments
                if comments or commit == last_commit:
                    # Inside db session for rollback
                    sync.post('repos/%s/reviews' % (pr_id,), data)
                if commit == last_commit:
                    break

            session.delete(message)
        sync.submitTask(SyncPullRequestTask(pr_id, priority=self.priority))

class SendMergeTask(Task):
    def __init__(self, pending_merge_key, priority=NORMAL_PRIORITY):
        super(SendMergeTask, self).__init__(priority)
        self.pending_merge_key = pending_merge_key

    def __repr__(self):
        return '<SendMergeTask %s>' % (self.pending_merge_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.pending_merge_key == self.pending_merge_key):
            return True
        return False

    def run(self, sync):
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
            sync.put('repos/%s/merge' % (pr_id,), data)

        sync.submitTask(SyncPullRequestTask(pr_id, priority=self.priority))

class PruneDatabaseTask(Task):
    def __init__(self, age, priority=NORMAL_PRIORITY):
        super(PruneDatabaseTask, self).__init__(priority)
        self.age = age

    def __repr__(self):
        return '<PruneDatabaseTask %s>' % (self.age,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.age == self.age):
            return True
        return False

    def run(self, sync):
        if not self.age:
            return
        app = sync.app
        with app.db.getSession() as session:
            for pr in session.getPullRequests('state:closed age:%s' % self.age):
                t = PrunePullRequestTask(pr.key, priority=self.priority)
                self.tasks.append(t)
                sync.submitTask(t)
        t = VacuumDatabaseTask(priority=self.priority)
        self.tasks.append(t)
        sync.submitTask(t)

class PrunePullRequestTask(Task):
    def __init__(self, key, priority=NORMAL_PRIORITY):
        super(PrunePullRequestTask, self).__init__(priority)
        self.key = key

    def __repr__(self):
        return '<PrunePullRequestTask %s>' % (self.key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.key == self.key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            pr = session.getPullRequest(self.key)
            if not pr:
                return
            repo = gitrepo.get_repo(pr.repository.name, app.config)
            self.log.info("Pruning %s pull request %s state:%s updated:%s" % (
                pr.repository.name, pr.number, pr.state, pr.updated))
            pr_ref = "pull/%s/head" % (pr.number,)
            self.log.info("Deleting %s ref %s" % (
                pr.repository.name, pr_ref))
            try:
                repo.deleteRef(pr_ref)
            except OSError as e:
                if e.errno not in [errno.EISDIR, errno.EPERM]:
                    raise
            session.delete(pr)

class VacuumDatabaseTask(Task):
    def __init__(self, priority=NORMAL_PRIORITY):
        super(VacuumDatabaseTask, self).__init__(priority)

    def __repr__(self):
        return '<VacuumDatabaseTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            session.vacuum()

class Sync(object):
    def __init__(self, app, disable_background_sync):
        self.user_agent = 'Hubtty/%s %s' % (hubtty.version.version_info.release_string(),
                                            requests.utils.default_user_agent())
        self.offline = False
        self.account_id = None
        self.app = app
        self.log = logging.getLogger('hubtty.sync')
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.result_queue = queue.Queue()
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'token ' + self.app.config.token})
        self.submitTask(SyncOwnAccountTask(HIGH_PRIORITY))
        if not disable_background_sync:
            self.submitTask(CheckReposTask(HIGH_PRIORITY))
            self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
            self.submitTask(SyncRepositoryListTask(HIGH_PRIORITY))
            self.submitTask(SyncSubscribedRepositoriesTask(NORMAL_PRIORITY))
            self.submitTask(SyncSubscribedRepositoryBranchesTask(LOW_PRIORITY))
            self.submitTask(SyncSubscribedRepositoryLabelsTask(LOW_PRIORITY))
            self.submitTask(SyncOutdatedPullRequestsTask(LOW_PRIORITY))
            self.submitTask(PruneDatabaseTask(self.app.config.expire_age, LOW_PRIORITY))
            self.periodic_thread = threading.Thread(target=self.periodicSync)
            self.periodic_thread.daemon = True
            self.periodic_thread.start()

    def periodicSync(self):
        hourly = time.time()
        while True:
            try:
                time.sleep(60)
                self.syncSubscribedRepositories()
                now = time.time()
                if now-hourly > 3600:
                    hourly = now
                    self.pruneDatabase()
                    self.syncOutdatedPullRequests()
            except Exception:
                self.log.exception('Exception in periodicSync')

    def submitTask(self, task):
        if not self.offline:
            if not self.queue.put(task, task.priority):
                task.complete(False)
        else:
            task.complete(False)

    def run(self, pipe):
        task = None
        while True:
            task = self._run(pipe, task)

    def _run(self, pipe, task=None):
        if not task:
            task = self.queue.get()
        self.log.debug('Run: %s' % (task,))
        try:
            task.run(self)
            task.complete(True)
            self.queue.complete(task)
        except (requests.ConnectionError, OfflineError, RateLimitError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ReadTimeout
        ) as e:
            self.log.warning("Offline due to: %s" % (e,))
            if not self.offline:
                self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
            self.offline = True
            self.app.status.update(offline=True, refresh=False)
            os.write(pipe, six.b('refresh\n'))
            time.sleep(30)
            return task
        except RestrictedError as e:
            task.complete(False)
            self.queue.complete(task)
            self.log.warning("Failed to run task %s: %s" % (task, e,))
            self.app.status.update(error=True, refresh=False)
        except Exception:
            task.complete(False)
            self.queue.complete(task)
            self.log.exception('Exception running task %s' % (task,))
            self.app.status.update(error=True, refresh=False)
        self.offline = False
        self.app.status.update(offline=False, refresh=False)
        for r in task.results:
            self.result_queue.put(r)
        os.write(pipe, six.b('refresh\n'))
        return None

    def url(self, path):
        return self.app.config.api_url + path

    def checkResponse(self, response):
        self.log.debug('HTTP status code: %d', response.status_code)
        if response.status_code == 503:
            raise OfflineError("Received 503 status code")
        elif response.status_code == 403:
            result = re.search(r"the `([\w-]+)` organization has enabled OAuth App access restrictions", response.text)
            if result:
                org = result.group(1)
                error_msg = "The '%s' organization has enabled third-party restrictions and has not yet approved Hubtty. Your review will be submitted again next time Hubtty starts. Create yourself a Personal Access Token to continue using Hubtty with this organization: https://hubtty.readthedocs.io/en/latest/authentication.html" % (org,)
                self.app.error(error_msg)
                raise RestrictedError("The '%s' organization has enabled third-party restrictions and has not yet approved hubtty" % (org,))
            else:
                raise Exception("Received %s status code: %s"
                        % (response.status_code, response.text))
        elif response.status_code >= 400:
            raise Exception("Received %s status code: %s"
                            % (response.status_code, response.text))

    def get(self, path, headers={}, response_callback=None):
        url = self.url(path)
        ret = None
        done = False

        default_headers = {
                'Accept': 'application/vnd.github.v3+json',
                'Accept-Encoding': 'gzip',
                'User-Agent': self.user_agent
                }

        if not response_callback:
            response_callback = self.checkResponse

        while not done:
            self.log.debug('GET: %s' % (url,))

            r = self.session.get(url,
                                 timeout=TIMEOUT,
                                 headers = {**default_headers, **headers})
            response_callback(r)
            if int(r.headers.get('X-RateLimit-Remaining', 1)) < 1:
                if r.headers.get('X-RateLimit-Reset'):
                    sleep = int(r.headers.get('X-RateLimit-Reset')) - int(time.time())
                    self.log.debug('Hit rate limit, retrying in %d seconds', sleep)
                    time.sleep(sleep)
                    continue
                else:
                    raise RateLimitError("Hitting RateLimit")

            # TODO(mandre) Check for incomplete results
            # https://docs.github.com/en/rest/reference/search#timeouts-and-incomplete-results
            if r.status_code == 200:
                result = json.loads(r.text)
                # Search queries will store results under the 'items' key
                if isinstance(result, dict) and 'items' in result:
                    result = result.get('items', [])
                if isinstance(ret, list):
                    ret.extend(result)
                else:
                    ret = result
                if len(result):
                    self.log.debug('200 OK, Received: %s' % (result,))
                else:
                    self.log.debug('200 OK, No body.')
            if 'next' in r.links.keys():
                url = r.links['next']['url']
            else:
                done = True
        return ret

    def post(self, path, data, headers={}, response_callback=None):
        url = self.url(path)
        default_headers = {
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json;charset=UTF-8',
                'User-Agent': self.user_agent
                }
        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('POST: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.post(url, data=json.dumps(data).encode('utf8'),
                              timeout=TIMEOUT,
                              headers = {**default_headers, **headers})
        response_callback(r)
        self.log.debug('Received: %s' % (r.text,))
        ret = None
        if r.text and len(r.text)>0:
            try:
                ret = json.loads(r.text)
            except Exception:
                self.log.exception("Unable to parse result %s from post to %s" %
                                   (r.text, url))
                raise
        return ret

    def put(self, path, data, headers={}, response_callback=None):
        url = self.url(path)
        default_headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'User-Agent': self.user_agent
                }
        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('PUT: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.put(url, data=json.dumps(data).encode('utf8'),
                             timeout=TIMEOUT,
                             headers = {**default_headers, **headers})
        response_callback(r)
        self.log.debug('Received: %s' % (r.text,))

    def patch(self, path, data, headers={}, response_callback=None):
        url = self.url(path)
        default_headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'User-Agent': self.user_agent
                }
        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('PATCH: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.patch(url, data=json.dumps(data).encode('utf8'),
                             timeout=TIMEOUT,
                             headers = {**default_headers, **headers})
        response_callback(r)
        self.log.debug('Received: %s' % (r.text,))

    def delete(self, path, data, headers={}, response_callback=None):
        url = self.url(path)
        default_headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'User-Agent': self.user_agent
                }
        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('DELETE: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.delete(url, data=json.dumps(data).encode('utf8'),
                                timeout=TIMEOUT,
                                headers = {**default_headers, **headers})
        response_callback(r)
        self.log.debug('Received: %s' % (r.text,))

    def syncSubscribedRepositories(self):
        task = SyncSubscribedRepositoriesTask(LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def pruneDatabase(self):
        task = PruneDatabaseTask(self.app.config.expire_age, LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def syncOutdatedPullRequests(self):
        task = SyncOutdatedPullRequestsTask(LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def query(self, query):
        q = 'search/issues?per_page=100&q=%s' % query
        self.log.debug('Query: %s' % (q,))
        return self.get(q)
