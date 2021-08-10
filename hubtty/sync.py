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
    def updateRelatedChanges(self, session, change):
        related_change_keys = set()
        related_change_keys.add(change.key)
        for commit in change.commits:
            parent = change.getCommitBySha(commit.parent)
            if parent:
                related_change_keys.add(parent.change.key)
            for child in session.getCommitsByParent(commit.commit):
                related_change_keys.add(child.change.key)
        self.related_change_keys = related_change_keys

class ProjectAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<ProjectAddedEvent project_key:%s>' % (
            self.project_key,)

    def __init__(self, project):
        self.project_key = project.key

class ChangeAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<ChangeAddedEvent project_key:%s change_key:%s>' % (
            self.project_key, self.change_key)

    def __init__(self, change):
        self.project_key = change.project.key
        self.change_key = change.key
        self.related_change_keys = set()
        self.review_flag_changed = True
        self.state_changed = True
        self.held_changed = False

class ChangeUpdatedEvent(UpdateEvent):
    def __repr__(self):
        return '<ChangeUpdatedEvent project_key:%s change_key:%s review_flag_changed:%s state_changed:%s>' % (
            self.project_key, self.change_key, self.review_flag_changed, self.state_changed)

    def __init__(self, change):
        self.project_key = change.project.key
        self.change_key = change.key
        self.related_change_keys = set()
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

class SyncProjectListTask(Task):
    def __repr__(self):
        return '<SyncProjectListTask>'

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
                self.log.error('Project %s does not exist or you do not have '
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
                project = session.getProjectByName(repo_name)
                if not project:
                    project = session.createProject(repo_name,
                                                    description=repo_desc)
                    self.log.info("Created project %s", repo_name)
                    self.results.append(ProjectAddedEvent(project))
                project.description = repo_desc
                project.can_push = remote_repo['permissions']['push']

            for p in session.getProjects():
                if p.name not in remote_repos_names:
                    self.log.info("Deleted project %s", p.name)
                    session.delete(p)

class SyncSubscribedProjectBranchesTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectBranchesTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for p in projects:
            sync.submitTask(SyncProjectBranchesTask(p.name, self.priority))

class SyncProjectBranchesTask(Task):
    def __init__(self, project_name, priority=NORMAL_PRIORITY):
        super(SyncProjectBranchesTask, self).__init__(priority)
        self.project_name = project_name

    def __repr__(self):
        return '<SyncProjectBranchesTask %s>' % (self.project_name,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_name == self.project_name):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('repos/%s/branches?per_page=100' % self.project_name)
        remote_branches = set()
        for b in remote:
            remote_branches.add(b['name'])
        with app.db.getSession() as session:
            local = {}
            project = session.getProjectByName(self.project_name)
            for branch in project.branches:
                local[branch.name] = branch
            local_branches = set(local.keys())

            for name in local_branches-remote_branches:
                session.delete(local[name])
                self.log.info("Deleted branch %s from project %s in local DB.", name, project.name)

            for name in remote_branches-local_branches:
                project.createBranch(name)
                self.log.info("Added branch %s to project %s in local DB.", name, project.name)

class SyncSubscribedProjectLabelsTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectLabelsTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for p in projects:
            sync.submitTask(SyncProjectLabelsTask(p.name, self.priority))

class SyncProjectLabelsTask(Task):
    def __init__(self, project_name, priority=NORMAL_PRIORITY):
        super(SyncProjectLabelsTask, self).__init__(priority)
        self.project_name = project_name

    def __repr__(self):
        return '<SyncProjectLabelsTask %s>' % (self.project_name,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_name == self.project_name):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote_labels = sync.get('repos/%s/labels' % (self.project_name,))
        with app.db.getSession() as session:
            project = session.getProjectByName(self.project_name)

            for remote_label in remote_labels:
                label = session.getLabel(remote_label['id'])
                if not label:
                    self.log.info("Created label %s for project %s", remote_label['name'], project.name)
                    project.createLabel(remote_label['id'], remote_label['name'],
                            remote_label['color'], remote_label['description'])
                else:
                    label.name = remote_label['name']
                    label.color = remote_label['color']
                    label.description = remote_label['description']

            # Delete old labels
            remote_label_ids = [l['id'] for l in remote_labels]
            for l in project.labels:
                if l.id not in remote_label_ids:
                    self.log.info("Deleted label %s", l.name)
                    session.delete(l)

class SyncSubscribedProjectsTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectsTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            keys = [p.key for p in session.getProjects(subscribed=True)]
        # Sync projects at most 10 at a time
        for i in range(0, len(keys), 10):
            t = SyncProjectTask(keys[i:i+10], self.priority)
            self.tasks.append(t)
            sync.submitTask(t)

class SyncProjectTask(Task):
    def __init__(self, project_keys, priority=NORMAL_PRIORITY):
        super(SyncProjectTask, self).__init__(priority)
        if type(project_keys) == int:
            project_keys = [project_keys]
        self.project_keys = project_keys

    def __repr__(self):
        return '<SyncProjectTask %s>' % (self.project_keys,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_keys == self.project_keys):
            return True
        return False

    def run(self, sync):
        app = sync.app
        now = datetime.datetime.utcnow()
        full_sync = []
        partial_sync = []
        sync_from = now
        with app.db.getSession() as session:
            for project_key in self.project_keys:
                project = session.getProject(project_key)
                if project.updated:
                    partial_sync.append(project.name)
                    # We can use the oldest sync time of the bunch, because
                    # when we sync projects individually when subscribing to
                    # them.
                    if project.updated < sync_from:
                        sync_from = project.updated
                else:
                    full_sync.append(project.name)

        def sync_projects(projects, query):
            for project_name in projects:
                query += ' repo:%s' % project_name
            changes = sync.query(query)
            for c in changes:
                sync.submitTask(SyncChangeTask(c['pull_request']['url'].split('repos/')[1], priority=self.priority))

        if full_sync:
            query = 'type:pr state:open'
            sync_projects(full_sync, query)

        if partial_sync:
            # Allow 4 seconds for request time, etc.
            query = 'type:pr updated:>%s' % ((sync_from - datetime.timedelta(seconds=4)).replace(microsecond=0).isoformat(),)
            sync_projects(partial_sync, query)

        for key in self.project_keys:
            sync.submitTask(SetProjectUpdatedTask(key, now, priority=self.priority))

class SetProjectUpdatedTask(Task):
    def __init__(self, project_key, updated, priority=NORMAL_PRIORITY):
        super(SetProjectUpdatedTask, self).__init__(priority)
        self.project_key = project_key
        self.updated = updated

    def __repr__(self):
        return '<SetProjectUpdatedTask %s %s>' % (self.project_key, self.updated)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_key == self.project_key and
            other.updated == self.updated):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            project.updated = self.updated

class SyncOutdatedChangesTask(Task):
    def __init__(self, priority=NORMAL_PRIORITY):
        super(SyncOutdatedChangesTask, self).__init__(priority)

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def __repr__(self):
        return '<SyncOutdatedChangesTask>'

    def run(self, sync):
        with sync.app.db.getSession() as session:
            for change in session.getOutdated():
                self.log.debug("Sync outdated change %s" % (change.change_id,))
                sync.submitTask(SyncChangeTask(change.change_id, priority=self.priority))

class SyncChangeTask(Task):
    def __init__(self, change_id, force_fetch=False, priority=NORMAL_PRIORITY):
        super(SyncChangeTask, self).__init__(priority)
        self.change_id = change_id
        self.force_fetch = force_fetch

    def __repr__(self):
        return '<SyncChangeTask %s>' % (self.change_id,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_id == self.change_id and
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
            self._syncChange(sync)
            end_time = time.time()
            total_time = end_time - start_time
            self.log.info("Synced change %s in %0.5f seconds.", self.change_id, total_time)
        except Exception:
            try:
                self.log.error("Marking change %s outdated" % (self.change_id,))
                with sync.app.db.getSession() as session:
                    change = session.getChangeByChangeID(self.change_id)
                    if change:
                        change.outdated = True
            except Exception:
                self.log.exception("Error while marking change %s as outdated" % (self.change_id,))
            raise

    def _syncChange(self, sync):
        app = sync.app
        remote_change = sync.get('repos/%s' % self.change_id)
        remote_commits = sync.get('repos/%s/commits?per_page=100' % self.change_id)
        remote_pr_comments = sync.get('repos/%s/comments?per_page=100' % self.change_id)
        remote_pr_reviews = sync.get('repos/%s/reviews?per_page=100' % self.change_id)
        remote_issue_comments = sync.get(('repos/%s/comments?per_page=100'
                                          % self.change_id).replace('/pulls/', '/issues/'))

        project_name = remote_change['base']['repo']['full_name']

        # Get commit details
        for commit in remote_commits:
            remote_commit_details = sync.get('repos/%s/commits/%s'
                    % (project_name, commit['sha']))
            commit['_hubtty_remote_commit_details'] = remote_commit_details

        # PR might have been rebased and no longer contain commits
        if len(remote_commits) > 0:
            last_commit = remote_commits[-1]
            last_commit['_hubtty_checks'] = []
            remote_commit_status = sync.get(
                    'repos/%s/commits/%s/status' % (project_name, last_commit['sha']))
            for check in remote_commit_status['statuses']:
                last_commit['_hubtty_checks'].append(self._checkResultFromStatus(check))
            remote_commit_check_runs = sync.get(
                    'repos/%s/commits/%s/check-runs' % (project_name, last_commit['sha']))
            for check in remote_commit_check_runs['check_runs']:
                last_commit['_hubtty_checks'].append(self._checkResultFromCheck(check))

        fetches = collections.defaultdict(list)
        with app.db.getSession() as session:
            change = session.getChangeByChangeID(self.change_id)
            if (remote_change.get('user') or {}).get('id'):
                account = session.getAccountByID(remote_change['user']['id'],
                                                 username=remote_change['user'].get('login'))
            else:
                account = session.getSystemAccount()

            if not change:
                project = session.getProjectByName(project_name)
                if not project:
                    self.log.debug("Project %s unknown while syncing change" % (project_name,))
                    remote_project = sync.get('repos/%s' % (project_name,))
                    if remote_project:
                        project = session.createProject(
                            remote_project['full_name'],
                            description=remote_project.get('description', ''))
                        self.log.info("Created project %s", project.name)
                        self.results.append(ProjectAddedEvent(project))
                        sync.submitTask(SyncProjectBranchesTask(project.name, self.priority))
                        sync.submitTask(SyncProjectLabelsTask(project.name, self.priority))
                created = dateutil.parser.parse(remote_change['created_at'])
                updated = dateutil.parser.parse(remote_change['updated_at'])
                change = project.createChange(remote_change['id'], account,
                                              remote_change['number'],
                                              remote_change['base']['ref'],
                                              self.change_id,
                                              remote_change['title'],
                                              (remote_change.get('body','') or '').replace('\r',''),
                                              created, updated,
                                              remote_change['state'],
                                              remote_change['additions'],
                                              remote_change['deletions'],
                                              remote_change['html_url'],
                                              remote_change['merged'],
                                              (remote_change['mergeable'] or False),
                                              )
                self.log.info("Created new change %s in local DB.", change.change_id)
                result = ChangeAddedEvent(change)
            else:
                result = ChangeUpdatedEvent(change)
            app.project_cache.clear(change.project)
            self.results.append(result)
            change.author = account
            if change.state != remote_change['state']:
                change.state = remote_change['state']
                result.state_changed = True
            change.title = remote_change['title']
            change.body = (remote_change.get('body','') or '').replace('\r','')
            change.updated = dateutil.parser.parse(remote_change['updated_at'])
            change.additions = remote_change['additions']
            change.deletions = remote_change['deletions']
            change.merged = remote_change['merged']
            change.mergeable = remote_change.get('mergeable') or False

            for label in remote_change['labels']:
                l = session.getLabel(label['id'])
                if l and l not in change.labels:
                    change.addLabel(l)
            remote_label_ids = [l['id'] for l in remote_change['labels']]
            for label in change.labels:
                if label.id not in remote_label_ids:
                    change.removeLabel(label)

            # Delete commits that no longer belong to the change
            remote_commits_sha = [c['sha'] for c in remote_commits]
            for commit in change.commits:
                if commit.sha not in remote_commits_sha:
                    self.log.info("Deleted commit %s", commit.sha)
                    session.delete(commit)

            repo = gitrepo.get_repo(change.project.name, app.config)
            for remote_commit in remote_commits:
                commit = change.getCommitBySha(remote_commit['sha'])
                # TODO: handle multiple parents
                url = sync.app.config.git_url + change.project.name
                ref = "pull/%s/head" % (change.number,)
                if (not commit) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not commit:
                    commit = change.createCommit((remote_commit['commit']['message'] or '').replace('\r',''),
                                                 remote_commit['sha'],
                                                 remote_commit['parents'][0]['sha'])
                    self.log.info("Created new commit %s for change %s in local DB.",
                                  commit.key, self.change_id)

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
                    associated_commit = change.getCommitBySha(remote_review['commit_id'])
                    if associated_commit:
                        associated_commit_id = associated_commit.key

                message = session.getMessageByID(remote_review['id'])
                if not message:
                    # Normalize date -> created
                    creation_date = remote_review.get('submitted_at', remote_review.get('created_at'))
                    if creation_date:
                        created = dateutil.parser.parse(creation_date)
                    message = change.createMessage(associated_commit_id, remote_review['id'], account, created,
                                                   (remote_review.get('body','') or '').replace('\r',''))
                    self.log.info("Created new review message %s for change %s in local DB.", message.key, change.change_id)
                else:
                    if message.author != account:
                        message.author = account
                    message.body = (remote_review.get('body','') or '').replace('\r','')

                review_state = remote_review.get('state')
                if review_state:
                    approval = session.getApproval(change, account, remote_review.get('commit_id'))
                    if approval:
                        approval.state = review_state
                    else:
                        change.createApproval(account, review_state, remote_review.get('commit_id'))
                        self.log.info("Created new approval for %s from %s commit %s.", change.change_id, account.username, remote_review.get('commit_id'))

            # Inline comments
            for remote_comment in remote_pr_comments:
                if (remote_comment.get('user') or {}).get('id'):
                    account = session.getAccountByID(remote_comment['user']['id'],
                                                     username=remote_comment['user'].get('login'))
                else:
                    account = session.getSystemAccount()
                comment = session.getCommentByID(remote_comment['id'])

                file_id = None
                associated_commit = change.getCommitBySha(remote_comment['commit_id'])
                if associated_commit:
                    fileobj = associated_commit.getFile(remote_comment['path'])
                    if fileobj is None:
                        fileobj = associated_commit.createFile(remote_comment['path'], 'modified')
                    file_id = fileobj.key

                updated = dateutil.parser.parse(remote_comment['updated_at'])
                if not comment:
                    created = dateutil.parser.parse(remote_comment['created_at'])
                    parent = False
                    if remote_comment.get('side', '') == 'PARENT':
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
                    self.log.info("Created new comment %s for change %s in local DB.",
                                    comment.key, change.change_id)
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

            change.outdated = False
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
    # on startup, check all projects
    #   for any subscribed project withot a local repo or if
    #   --fetch-missing-refs is supplied, check all local changes for
    #   missing refs, and sync the associated changes
    def __repr__(self):
        return '<CheckReposTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for project in projects:
            try:
                missing = False
                try:
                    gitrepo.get_repo(project.name, app.config)
                except gitrepo.GitCloneError:
                    missing = True
                if missing or app.fetch_missing_refs:
                    sync.submitTask(
                        CheckCommitsTask(project.key,
                                           force_fetch=app.fetch_missing_refs,
                                           priority=LOW_PRIORITY)
                    )
            except Exception:
                self.log.exception("Exception checking repo %s" %
                                   (project.name,))

class CheckCommitsTask(Task):
    def __init__(self, project_key, force_fetch=False,
                 priority=NORMAL_PRIORITY):
        super(CheckCommitsTask, self).__init__(priority)
        self.project_key = project_key
        self.force_fetch = force_fetch

    def __repr__(self):
        return '<CheckCommitsTask %s>' % (self.project_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_key == self.project_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        to_sync = set()
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            repo = None
            try:
                repo = gitrepo.get_repo(project.name, app.config)
            except gitrepo.GitCloneError:
                pass
            for change in project.open_changes:
                if repo:
                    for commit in change.commits:
                        if repo.checkCommits([commit.parent, commit.sha]):
                            to_sync.add(change.change_id)
                else:
                    to_sync.add(change.change_id)
        for change_id in to_sync:
            sync.submitTask(SyncChangeTask(change_id,
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
                sync.submitTask(RebaseChangeTask(c.key, self.priority))
            for c in session.getPendingPullRequestEdits():
                sync.submitTask(EditPullRequestTask(c.key, self.priority))
            for c in session.getPendingMerges():
                sync.submitTask(SendMergeTask(c.key, self.priority))
            for m in session.getPendingMessages():
                sync.submitTask(UploadReviewTask(m.key, self.priority))

class SetLabelsTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(SetLabelsTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<SetLabelsTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        # Set labels using local ones as source of truth
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            local_labels = [l.name for l in change.labels]

            data = dict(labels=local_labels)
            change.pending_labels = False
            # Inside db session for rollback
            sync.put(('repos/%s/labels' % change.change_id).replace('/pulls/', '/issues/'),
                    data)
            sync.submitTask(SyncChangeTask(change.change_id, priority=self.priority))

class RebaseChangeTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(RebaseChangeTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<RebaseChangeTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        def checkResponse(response):
            self.log.debug('HTTP status code: %d', response.status_code)
            if response.status_code == 503:
                raise OfflineError("Received 503 status code")
            elif response.status_code == 422:
                error_msg = 'Failed to rebase change %s: %s' % (change.change_id, response.json()['message'])
                app.error(error_msg)
                self.log.error(error_msg)
            elif response.status_code >= 400:
                raise Exception("Received %s status code: %s"
                                % (response.status_code, response.text))

        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.pending_rebase = False
            latest_commit = change.commits[-1]
            if latest_commit:
                headers = {'Accept': 'application/vnd.github.lydian-preview+json'}
                # Inside db session for rollback
                sync.put('repos/%s/update-branch' % (change.change_id,), {
                    'expected_head_sha': latest_commit.sha,
                    }, headers=headers, response_callback=checkResponse)
                sync.submitTask(SyncChangeTask(change.change_id, priority=self.priority))

class EditPullRequestTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(EditPullRequestTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<EditPullRequestTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            if change.pending_edit_message:
                sync.post(('repos/%s/comments' % change.change_id).replace('/pulls/', '/issues/'),
                        {'body': change.pending_edit_message})

            change.pending_edit = False
            change.pending_edit_message = None
            edit_params = {
                    'title': change.title,
                    'body': change.body
                    }
            if change.state == 'closed':
                edit_params['state'] = 'close'
            elif change.state == 'open':
                edit_params['state'] = 'open'
            # Inside db session for rollback
            sync.patch('repos/%s' % (change.change_id,), edit_params)
            sync.submitTask(SyncChangeTask(change.change_id, priority=self.priority))

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
            change = message.commit.change
        if not change.held:
            self.log.debug("Syncing %s to find out if it should be held" % (change.change_id,))
            t = SyncChangeTask(change.change_id)
            t.run(sync)
            self.results += t.results
        change_id = None
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            commit = message.commit
            change = message.commit.change
            if change.held:
                self.log.debug("Not uploading review to %s because it is held" %
                               (change.change_id,))
                return
            change_id = change.change_id
            current_commit = change.commits[-1]
            data = dict(commit_id=current_commit.sha,
                        body=message.message)
            if commit == current_commit:
                for approval in change.draft_approvals:
                    data['event'] = approval.state
                    session.delete(approval)
            comments = []
            for file in commit.files:
                if file.draft_comments:
                    for comment in file.draft_comments:
                        d = dict(path=file.path,
                                 line=comment.line,
                                 body=comment.message)
                        if comment.parent:
                            d['side'] = 'PARENT'
                        comments.append(d)
                        session.delete(comment)
            if comments:
                data['comments'] = comments
            session.delete(message)
            # Inside db session for rollback
            sync.post('repos/%s/reviews' % (change_id,),
                      data)
        sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

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
        change_id = None
        with app.db.getSession() as session:
            pm = session.getPendingMerge(self.pending_merge_key)
            data = dict(sha=pm.sha, merge_method=pm.merge_method)
            if pm.commit_title:
                data['commit_title'] = pm.commit_title
            if pm.commit_message:
                data['commit_message'] = pm.commit_message
            change_id = pm.change.change_id
            session.delete(pm)
            # Inside db session for rollback
            sync.put('repos/%s/merge' % (change_id,), data)

        sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

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
            for change in session.getChanges('state:closed age:%s' % self.age):
                t = PruneChangeTask(change.key, priority=self.priority)
                self.tasks.append(t)
                sync.submitTask(t)
        t = VacuumDatabaseTask(priority=self.priority)
        self.tasks.append(t)
        sync.submitTask(t)

class PruneChangeTask(Task):
    def __init__(self, key, priority=NORMAL_PRIORITY):
        super(PruneChangeTask, self).__init__(priority)
        self.key = key

    def __repr__(self):
        return '<PruneChangeTask %s>' % (self.key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.key == self.key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.key)
            if not change:
                return
            repo = gitrepo.get_repo(change.project.name, app.config)
            self.log.info("Pruning %s change %s state:%s updated:%s" % (
                change.project.name, change.number, change.state, change.updated))
            change_ref = "pull/%s/head" % (change.number,)
            self.log.info("Deleting %s ref %s" % (
                change.project.name, change_ref))
            try:
                repo.deleteRef(change_ref)
            except OSError as e:
                if e.errno not in [errno.EISDIR, errno.EPERM]:
                    raise
            session.delete(change)

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
            self.submitTask(SyncProjectListTask(HIGH_PRIORITY))
            self.submitTask(SyncSubscribedProjectsTask(NORMAL_PRIORITY))
            self.submitTask(SyncSubscribedProjectBranchesTask(LOW_PRIORITY))
            self.submitTask(SyncSubscribedProjectLabelsTask(LOW_PRIORITY))
            self.submitTask(SyncOutdatedChangesTask(LOW_PRIORITY))
            self.submitTask(PruneDatabaseTask(self.app.config.expire_age, LOW_PRIORITY))
            self.periodic_thread = threading.Thread(target=self.periodicSync)
            self.periodic_thread.daemon = True
            self.periodic_thread.start()

    def periodicSync(self):
        hourly = time.time()
        while True:
            try:
                time.sleep(60)
                self.syncSubscribedProjects()
                now = time.time()
                if now-hourly > 3600:
                    hourly = now
                    self.pruneDatabase()
                    self.syncOutdatedChanges()
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

    def syncSubscribedProjects(self):
        task = SyncSubscribedProjectsTask(LOW_PRIORITY)
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

    def syncOutdatedChanges(self):
        task = SyncOutdatedChangesTask(LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def query(self, query):
        q = 'search/issues?per_page=100&q=%s' % query
        self.log.debug('Query: %s' % (q,))
        response = self.get(q)
        return response.get('items', [])
