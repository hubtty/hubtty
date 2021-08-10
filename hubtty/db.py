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

import re
import time
import logging
import threading

import alembic
import alembic.config
import six
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.schema import ForeignKey
from sqlalchemy.orm import mapper, sessionmaker, relationship, scoped_session, joinedload
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import exists
from sqlalchemy.sql.expression import and_

from hubtty import sync

metadata = MetaData()
project_table = Table(
    'project', metadata,
    Column('key', Integer, primary_key=True),
    Column('name', String(255), index=True, unique=True, nullable=False),
    Column('subscribed', Boolean, index=True, default=False),
    Column('description', Text, nullable=False, default=''),
    Column('can_push', Boolean, default=False),
    Column('updated', DateTime),
    )
branch_table = Table(
    'branch', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('name', String(255), index=True, nullable=False),
    )
topic_table = Table(
    'topic', metadata,
    Column('key', Integer, primary_key=True),
    Column('name', String(255), index=True, nullable=False),
    Column('sequence', Integer, index=True, unique=True, nullable=False),
    )
project_topic_table = Table(
    'project_topic', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('topic_key', Integer, ForeignKey("topic.key"), index=True),
    Column('sequence', Integer, nullable=False),
    UniqueConstraint('topic_key', 'sequence', name='topic_key_sequence_const'),
    )
change_table = Table(
    'change', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('id', Integer, index=True, unique=True, nullable=False),
    Column('number', Integer, index=True, nullable=False),
    Column('branch', String(255), index=True, nullable=False),
    Column('change_id', String(255), index=True, unique=True, nullable=False),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('title', String(255), nullable=False),
    Column('body', Text, nullable=False),
    Column('created', DateTime, index=True, nullable=False),
    Column('updated', DateTime, index=True, nullable=False),
    Column('state', String(16), index=True, nullable=False),
    Column('additions', Integer, nullable=False),
    Column('deletions', Integer, nullable=False),
    Column('html_url', Text, nullable=False),
    Column('hidden', Boolean, index=True, nullable=False),
    Column('reviewed', Boolean, index=True, nullable=False),
    Column('starred', Boolean, index=True, nullable=False),
    Column('held', Boolean, index=True, nullable=False),
    Column('pending_rebase', Boolean, index=True, nullable=False),
    Column('pending_edit', Boolean, index=True, nullable=False),
    Column('pending_labels', Boolean, index=True, nullable=False),
    Column('pending_edit_message', Text),
    Column('last_seen', DateTime, index=True),
    Column('outdated', Boolean, index=True, nullable=False),
    Column('merged', Boolean, index=True, nullable=False),
    Column('mergeable', Boolean, index=True, nullable=False),
    )
commit_table = Table(
    'commit', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('message', Text, nullable=False),
    Column('sha', String(64), index=True, nullable=False),
    Column('parent', String(64), index=True, nullable=False),
    )
message_table = Table(
    'message', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('commit_key', Integer, ForeignKey("commit.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', Integer, index=True), #, unique=True, nullable=False),
    Column('created', DateTime, index=True, nullable=False),
    Column('message', Text, nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    Column('pending', Boolean, index=True, nullable=False),
    )
comment_table = Table(
    'comment', metadata,
    Column('key', Integer, primary_key=True),
    Column('message_key', Integer, ForeignKey("message.key"), index=True),
    Column('file_key', Integer, ForeignKey("file.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', Integer, index=True), #, unique=True, nullable=False),
    Column('in_reply_to', Integer, index=True),
    Column('created', DateTime, index=True, nullable=False),
    Column('updated', DateTime, nullable=False),
    Column('parent', Boolean, nullable=False),
    Column('commit_id', String(64), nullable=False),
    Column('original_commit_id', String(64), nullable=False),
    Column('line', Integer, index=True),
    Column('original_line', Integer),
    Column('message', Text, nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    Column('url', Text()),
    )
approval_table = Table(
    'approval', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('state', String(32), index=True, nullable=False),
    Column('sha', String(64), nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    UniqueConstraint('change_key', 'account_key', 'sha', name='approval_change_key_account_key_sha_const'),
    )
account_table = Table(
    'account', metadata,
    Column('key', Integer, primary_key=True),
    Column('id', Integer, index=True, unique=True, nullable=False),
    Column('name', String(255), index=True),
    Column('username', String(255), index=True),
    Column('email', String(255), index=True),
    )
pending_merge_table = Table(
    'pending_merge', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('commit_title', String(255)),
    Column('commit_message', Text),
    Column('sha', String(255), nullable=False),
    Column('merge_method', String(255), nullable=False),
    )
file_table = Table(
    'file', metadata,
    Column('key', Integer, primary_key=True),
    Column('commit_key', Integer, ForeignKey("commit.key"), index=True),
    Column('path', Text, nullable=False, index=True),
    Column('old_path', Text, index=True),
    Column('inserted', Integer),
    Column('deleted', Integer),
    Column('status', String(16), index=True, nullable=False),
    )
server_table = Table(
    'server', metadata,
    Column('key', Integer, primary_key=True),
    Column('own_account_key', Integer, ForeignKey("account.key"), index=True),
    )
check_table = Table(
    'check', metadata,
    Column('key', Integer, primary_key=True),
    Column('commit_key', Integer, ForeignKey("commit.key"), index=True),
    Column('state', String(16), nullable=False),
    Column('name', String(255), index=True),
    Column('url', Text),
    Column('message', Text),
    Column('started', DateTime),
    Column('finished', DateTime),
    Column('created', DateTime, nullable=False),
    Column('updated', DateTime, nullable=False),
    )
label_table = Table(
    'label', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('id', Integer, nullable=False, index=True),
    Column('name', String(length=255), nullable=False),
    Column('color', String(length=8), nullable=False),
    Column('description', Text),
    )
change_label_table = Table(
    'change_label', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('label_key', Integer, ForeignKey("label.key"), index=True),
    UniqueConstraint('change_key', 'label_key', name='change_key_label_key_const'),
    )


class Account(object):
    def __init__(self, id, name=None, username=None, email=None):
        self.id = id
        self.name = name
        self.username = username
        self.email = email

class Project(object):
    def __init__(self, name, subscribed=False, description='', can_push=False):
        self.name = name
        self.subscribed = subscribed
        self.description = description
        self.can_push = can_push

    def createChange(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Change(*args, **kw)
        self.changes.append(c)
        session.add(c)
        session.flush()
        return c

    def createBranch(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        b = Branch(*args, **kw)
        self.branches.append(b)
        session.add(b)
        session.flush()
        return b

    def createLabel(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        l = Label(*args, **kw)
        self.labels.append(l)
        session.add(l)
        session.flush()
        return l

class Branch(object):
    def __init__(self, project, name):
        self.project_key = project.key
        self.name = name

class ProjectTopic(object):
    def __init__(self, project, topic, sequence):
        self.project_key = project.key
        self.topic_key = topic.key
        self.sequence = sequence

class Topic(object):
    def __init__(self, name, sequence):
        self.name = name
        self.sequence = sequence

    def addProject(self, project):
        session = Session.object_session(self)
        seq = max([x.sequence for x in self.project_topics] + [0])
        pt = ProjectTopic(project, self, seq+1)
        self.project_topics.append(pt)
        self.projects.append(project)
        session.add(pt)
        session.flush()

    def removeProject(self, project):
        session = Session.object_session(self)
        for pt in self.project_topics:
            if pt.project_key == project.key:
                self.project_topics.remove(pt)
                session.delete(pt)
        self.projects.remove(project)
        session.flush()

class Label(object):
    def __init__(self, project, id, name, color, description=None):
        self.project_key = project.key
        self.id = id
        self.name = name
        self.color = color
        self.description = description

class ChangeLabel(object):
    def __init__(self, change, label):
        self.change_key = change.key
        self.label_key = label.key

class Change(object):
    def __init__(self, project, id, author, number, branch, change_id,
                 title, body, created, updated, state, additions, deletions,
                 html_url, merged, mergeable, hidden=False, reviewed=False,
                 starred=False, held=False, pending_rebase=False,
                 pending_edit=False, pending_edit_message=None,
                 pending_labels=False, outdated=False):
        self.project_key = project.key
        self.account_key = author.key
        self.id = id
        self.number = number
        self.branch = branch
        self.change_id = change_id
        self.title = title
        self.body = body
        self.created = created
        self.updated = updated
        self.state = state
        self.additions = additions
        self.deletions = deletions
        self.html_url = html_url
        self.hidden = hidden
        self.reviewed = reviewed
        self.starred = starred
        self.held = held
        self.pending_rebase = pending_rebase
        self.pending_labels = pending_labels
        self.pending_edit = pending_edit
        self.pending_edit_message = pending_edit_message
        self.outdated = outdated
        self.merged = merged
        self.mergeable = mergeable

    def getReviewState(self):
        last_commit = self.commits[-1].sha
        approvals = [a.state for a in self.approvals if a.sha == last_commit]
        if 'APPROVED' in approvals or 'APPROVE' in approvals:
            return 'APPROVED'
        elif 'CHANGES_REQUESTED' in approvals or 'REQUEST_CHANGES' in approvals:
            return 'CHANGES_REQUESTED'
        elif approvals:
            return 'COMMENTED'
        return ''

    def getCommitBySha(self, sha):
        for commit in self.commits:
            if commit.sha == sha:
                return commit
        return None

    def createCommit(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        r = Commit(*args, **kw)
        self.commits.append(r)
        session.add(r)
        session.flush()
        return r

    def createMessage(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        m = Message(*args, **kw)
        self.messages.append(m)
        session.add(m)
        session.flush()
        return m

    def createApproval(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        l = Approval(*args, **kw)
        self.approvals.append(l)
        session.add(l)
        session.flush()
        return l

    def createPendingMerge(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        pm = PendingMerge(*args, **kw)
        self.pending_merge.append(pm)
        session.add(pm)
        session.flush()
        return pm

    def addLabel(self, label):
        session = Session.object_session(self)
        cl = ChangeLabel(self, label)
        self.change_labels.append(cl)
        self.labels.append(label)
        session.add(cl)
        session.flush()

    def removeLabel(self, label):
        session = Session.object_session(self)

        for cl in self.change_labels:
            if cl.label_key == label.key:
                self.change_labels.remove(cl)
                session.delete(cl)
        self.labels.remove(label)
        session.flush()

    def isValid(self):
        # This might happen when the sync was partial, i.e. we hit rate limit
        # or the connection dropped
        return len(self.commits) > 0

    def canMerge(self):
        return self.mergeable and self.project.can_push

    @property
    def author_name(self):
        author_name = 'Anonymous Coward'
        if self.author:
            if self.author.name:
                author_name = self.author.name
            elif self.author.username:
                author_name = self.author.username
            elif self.author.email:
                author_name = self.author.email
        return author_name

class Commit(object):
    def __init__(self, change, message, sha, parent):
        self.change_key = change.key
        self.message = message
        self.sha = sha
        self.parent = parent

    def createFile(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        f = File(*args, **kw)
        self.files.append(f)
        session.add(f)
        session.flush()
        if hasattr(self, '_file_cache'):
            self._file_cache[f.path] = f
        return f

    def createCheck(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Check(*args, **kw)
        self.checks.append(c)
        session.add(c)
        session.flush()
        return c

    def getFile(self, path):
        if not hasattr(self, '_file_cache'):
            self._file_cache = {}
            for f in self.files:
                self._file_cache[f.path] = f
        return self._file_cache.get(path, None)

    def getPendingMessage(self):
        for m in self.messages:
            if m.pending:
                return m
        return None

    def getDraftMessage(self):
        for m in self.messages:
            if m.draft:
                return m
        return None


class Message(object):
    def __init__(self, change, commit_id, id, author, created, message, draft=False, pending=False):
        self.change_key = change.key
        self.commit_key = commit_id
        self.account_key = author.key
        self.id = id
        self.created = created
        self.message = message
        self.draft = draft
        self.pending = pending

    @property
    def author_name(self):
        author_name = 'Anonymous Coward'
        if self.author:
            if self.author.name:
                author_name = self.author.name
            elif self.author.username:
                author_name = self.author.username
            elif self.author.email:
                author_name = self.author.email
        return author_name

    def createComment(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Comment(*args, **kw)
        self.comments.append(c)
        session.add(c)
        session.flush()
        return c

class Comment(object):
    def __init__(self, message_obj, file_id, id, author, in_reply_to, created,
                 updated, parent, commit_id, original_commit_id, line,
                 original_line, message, draft=False, url=None):
        self.message_key = message_obj.key
        self.file_key = file_id
        self.account_key = author.key
        self.id = id
        self.in_reply_to = in_reply_to
        self.created = created
        self.updated = updated
        self.parent = parent
        self.commit_id = commit_id
        self.original_commit_id = original_commit_id
        self.line = line
        self.original_line = original_line
        self.message = message
        self.draft = draft
        self.url = url

class Approval(object):
    def __init__(self, change, reviewer, state, sha, draft=False):
        self.change_key = change.key
        self.account_key = reviewer.key
        self.state = state
        self.sha = sha
        self.draft = draft

    @property
    def reviewer_name(self):
        reviewer_name = 'Anonymous Coward'
        if self.reviewer:
            if self.reviewer.name:
                reviewer_name = self.reviewer.name
            elif self.reviewer.username:
                reviewer_name = self.reviewer.username
            elif self.reviewer.email:
                reviewer_name = self.reviewer.email
        return reviewer_name

class PendingMerge(object):
    def __init__(self, change, sha, merge_method, commit_title=None,
            commit_message=None):
        self.change_key = change.key
        self.commit_title = commit_title
        self.commit_message = commit_message
        self.sha = sha
        self.merge_method = merge_method

class File(object):
    def __init__(self, commit, path, status, old_path=None,
                 inserted=None, deleted=None):
        self.commit_key = commit.key
        self.path = path
        self.status = status
        self.old_path = old_path
        self.inserted = inserted
        self.deleted = deleted

    @property
    def display_path(self):
        if not self.old_path:
            return self.path
        pre = []
        post = []
        for start in range(min(len(self.old_path), len(self.path))):
            if self.path[start] == self.old_path[start]:
                pre.append(self.old_path[start])
            else:
                break
        pre = ''.join(pre)
        for end in range(1, min(len(self.old_path), len(self.path))-1):
            if self.path[0-end] == self.old_path[0-end]:
                post.insert(0, self.old_path[0-end])
            else:
                break
        post = ''.join(post)
        mid = '{%s => %s}' % (self.old_path[start:0-end+1], self.path[start:0-end+1])
        if pre and post:
            mid = '{%s => %s}' % (self.old_path[start:0-end+1],
                                  self.path[start:0-end+1])
            return pre + mid + post
        else:
            return '%s => %s' % (self.old_path, self.path)

class Server(object):
    def __init__(self):
        pass

class Check(object):
    def __init__(self, commit, name, state, created, updated):
        self.commit_key = commit.key
        self.name = name
        self.state = state
        self.created = created
        self.updated = updated

mapper(Account, account_table)
mapper(Project, project_table, properties=dict(
    branches=relationship(Branch, backref='project',
                          order_by=branch_table.c.name,
                          cascade='all, delete-orphan'),
    changes=relationship(Change, backref='project',
                         order_by=change_table.c.number,
                         cascade='all, delete-orphan'),
    labels=relationship(Label, backref='project',
                          order_by=label_table.c.name,
                          cascade='all, delete-orphan'),
    topics=relationship(Topic,
                        secondary=project_topic_table,
                        order_by=topic_table.c.name,
                        viewonly=True),
    unreviewed_changes=relationship(Change,
                                    primaryjoin=and_(project_table.c.key==change_table.c.project_key,
                                                     change_table.c.hidden==False,
                                                     change_table.c.state=='open',
                                                     change_table.c.reviewed==False),
                                    order_by=change_table.c.number,
                                ),
    open_changes=relationship(Change,
                              primaryjoin=and_(project_table.c.key==change_table.c.project_key,
                                               change_table.c.state=='open'),
                              order_by=change_table.c.number,
                          ),
))
mapper(Branch, branch_table)
mapper(Topic, topic_table, properties=dict(
    projects=relationship(Project,
                          secondary=project_topic_table,
                          order_by=project_table.c.name,
                          viewonly=True),
    project_topics=relationship(ProjectTopic),
))
mapper(ProjectTopic, project_topic_table)
mapper(Change, change_table, properties=dict(
        author=relationship(Account),
        commits=relationship(Commit, backref='change',
                             cascade='all, delete-orphan'),
        messages=relationship(Message, backref='change',
                             order_by=message_table.c.created,
                              cascade='all, delete-orphan'),
        approvals=relationship(Approval, backref='change',
                               order_by=approval_table.c.state,
                               cascade='all, delete-orphan'),
        pending_merge=relationship(PendingMerge, backref='change',
                                   cascade='all, delete-orphan'),
        labels=relationship(Label,
                            secondary=change_label_table,
                            order_by=label_table.c.name,
                            viewonly=True),
        change_labels=relationship(ChangeLabel),
        draft_approvals=relationship(Approval,
                                     primaryjoin=and_(change_table.c.key==approval_table.c.change_key,
                                                      approval_table.c.draft==True),
                                     order_by=approval_table.c.state)
        ))
mapper(Commit, commit_table, properties=dict(
        messages=relationship(Message, backref='commit',
                              order_by=message_table.c.created,
                              cascade='all, delete-orphan'),
        files=relationship(File, backref='commit',
                           cascade='all, delete-orphan'),
        checks=relationship(Check, backref='commit',
                            order_by=check_table.c.name,
                            cascade='all, delete-orphan'),

        ))
mapper(Message, message_table, properties=dict(
        author=relationship(Account),
        comments=relationship(Comment, backref='change',
                              order_by=comment_table.c.created,
                              cascade='all, delete-orphan'),
        ))
mapper(File, file_table, properties=dict(
       comments=relationship(Comment, backref='file',
                             order_by=(comment_table.c.line,
                                       comment_table.c.created),
                             cascade='all, delete-orphan'),
       current_comments=relationship(Comment,
                                     primaryjoin=and_(file_table.c.key==comment_table.c.file_key,
                                                      comment_table.c.line>0),
                                     order_by=(comment_table.c.line,
                                               comment_table.c.created)),
       draft_comments=relationship(Comment,
                                   primaryjoin=and_(file_table.c.key==comment_table.c.file_key,
                                                    comment_table.c.draft==True),
                                   order_by=(comment_table.c.line,
                                             comment_table.c.created)),
       ))

mapper(Comment, comment_table, properties=dict(
        author=relationship(Account)))
mapper(Approval, approval_table, properties=dict(
        reviewer=relationship(Account)))
mapper(PendingMerge, pending_merge_table)
mapper(Server, server_table, properties=dict(
    own_account=relationship(Account)
    ))
mapper(Check, check_table)
mapper(Label, label_table)
mapper(ChangeLabel, change_label_table)


def match(expr, item):
    if item is None:
        return False
    return re.match(expr, item) is not None

@sqlalchemy.event.listens_for(sqlalchemy.engine.Engine, "connect")
def add_sqlite_match(dbapi_connection, connection_record):
    dbapi_connection.create_function("matches", 2, match)


class Database(object):
    def __init__(self, app, dburi, search):
        self.log = logging.getLogger('hubtty.db')
        self.own_account_key = None
        self.dburi = dburi
        self.search = search
        self.engine = create_engine(self.dburi)
        self.app = app
        #metadata.create_all(self.engine)
        self.migrate(app)
        # If we want the objects returned from query() to be usable
        # outside of the session, we need to expunge them from the session,
        # and since the DatabaseSession always calls commit() on the session
        # when the context manager exits, we need to inform the session to
        # expire objects when it does so.
        self.session_factory = sessionmaker(bind=self.engine,
                                            expire_on_commit=False,
                                            autoflush=False)
        self.session = scoped_session(self.session_factory)
        self.lock = threading.Lock()

    def getSession(self):
        return DatabaseSession(self)

    def migrate(self, app):
        conn = self.engine.connect()
        context = alembic.migration.MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        self.log.debug('Current migration revision: %s' % current_rev)

        has_table = self.engine.dialect.has_table(conn, "project")

        config = alembic.config.Config()
        config.set_main_option("script_location", "hubtty:alembic")
        config.set_main_option("sqlalchemy.url", self.dburi)
        config.hubtty_app = app

        if current_rev is None and has_table:
            self.log.debug('Stamping database as initial revision')
            alembic.command.stamp(config, "44402069e137")
        alembic.command.upgrade(config, 'head')

class DatabaseSession(object):
    def __init__(self, database):
        self.database = database
        self.session = database.session
        self.search = database.search

    def __enter__(self):
        self.database.lock.acquire()
        self.start = time.time()
        return self

    def __exit__(self, etype, value, tb):
        if etype:
            self.session().rollback()
        else:
            self.session().commit()
        self.session().close()
        self.session = None
        end = time.time()
        self.database.log.debug("Database lock held %s seconds" % (end-self.start,))
        self.database.lock.release()

    def abort(self):
        self.session().rollback()

    def commit(self):
        self.session().commit()

    def delete(self, obj):
        self.session().delete(obj)

    def vacuum(self):
        self.session().execute("VACUUM")

    def getProjects(self, subscribed=False, unreviewed=False, topicless=False):
        """Retrieve projects.

        :param subscribed: If True limit to only subscribed projects.
        :param unreviewed: If True limit to only projects with unreviewed
            changes.
        :param topicless: If True limit to only projects without topics.
        """
        query = self.session().query(Project)
        if subscribed:
            query = query.filter_by(subscribed=subscribed)
            if unreviewed:
                query = query.filter(exists().where(Project.unreviewed_changes))
        if topicless:
            query = query.filter_by(topics=None)
        return query.order_by(Project.name).all()

    def getTopics(self):
        return self.session().query(Topic).order_by(Topic.sequence).all()

    def getProject(self, key):
        try:
            return self.session().query(Project).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getProjectByName(self, name):
        try:
            return self.session().query(Project).filter_by(name=name).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getTopic(self, key):
        try:
            return self.session().query(Topic).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getTopicByName(self, name):
        try:
            return self.session().query(Topic).filter_by(name=name).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChange(self, key, lazy=True):
        query = self.session().query(Change).filter_by(key=key)
        if not lazy:
            query = query.options(joinedload(Change.commits).joinedload(Commit.files).joinedload(File.comments))
        try:
            return query.one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChangeByChangeID(self, change_id):
        try:
            return self.session().query(Change).filter_by(change_id=change_id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChangeIDs(self, ids):
        # Returns a set of IDs that exist in the local database matching
        # the set of supplied IDs. This is used when sync'ing the changesets
        # locally with the remote changes.
        if not ids:
            return set()
        query = self.session().query(Change.id)
        return set(ids).intersection(r[0] for r in query.all())

    def getChangesByChangeID(self, change_id):
        try:
            return self.session().query(Change).filter_by(change_id=change_id)
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getPendingMerge(self, key):
        try:
            return self.session().query(PendingMerge).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChanges(self, query, unreviewed=False, sort_by='number'):
        self.database.log.debug("Search query: %s sort: %s" % (query, sort_by))
        q = self.session().query(Change).filter(self.search.parse(query))
        if not isinstance(sort_by, (list, tuple)):
            sort_by = [sort_by]
        if unreviewed:
            q = q.filter(change_table.c.hidden==False, change_table.c.reviewed==False)
        for s in sort_by:
            if s == 'updated':
                q = q.order_by(change_table.c.updated)
            elif s == 'last-seen':
                q = q.order_by(change_table.c.last_seen)
            elif s == 'number':
                q = q.order_by(change_table.c.number)
            elif s == 'project':
                q = q.filter(project_table.c.key == change_table.c.project_key)
                q = q.order_by(project_table.c.name)
        self.database.log.debug("Search SQL: %s" % q)
        try:
            validChanges = []
            for c in q.all():
                if c.isValid():
                    validChanges.append(c)
                else:
                    self.database.app.sync.submitTask(
                        sync.SyncChangeTask(c.change_id, priority=sync.HIGH_PRIORITY))
            return validChanges
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getCommit(self, key):
        try:
            return self.session().query(Commit).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getCommitsBySha(self, sha):
        try:
            return self.session().query(Commit).filter_by(sha=sha).all()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getCommitsByParent(self, parent):
        if isinstance(parent, six.string_types):
            parent = (parent,)
        try:
            return self.session().query(Commit).filter(Commit.parent.in_(parent)).all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getFile(self, key):
        try:
            return self.session().query(File).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getComment(self, key):
        try:
            return self.session().query(Comment).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getCommentByID(self, id):
        try:
            return self.session().query(Comment).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getMessage(self, key):
        try:
            return self.session().query(Message).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getMessageByID(self, id):
        try:
            return self.session().query(Message).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getApproval(self, change, account, sha):
        try:
            return self.session().query(Approval).filter_by(
                change_key=change.key, account_key=account.key, sha=sha).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getHeld(self):
        return self.session().query(Change).filter_by(held=True).all()

    def getOutdated(self):
        return self.session().query(Change).filter_by(outdated=True).all()

    def getPendingMessages(self):
        return self.session().query(Message).filter_by(pending=True).all()

    def getPendingLabels(self):
        return self.session().query(Change).filter_by(pending_labels=True).all()

    def getPendingRebases(self):
        return self.session().query(Change).filter_by(pending_rebase=True).all()

    def getPendingPullRequestEdits(self):
        return self.session().query(Change).filter_by(pending_edit=True).all()

    def getPendingMerges(self):
        return self.session().query(PendingMerge).all()

    def getAccounts(self):
        return self.session().query(Account).all()

    def getAccountByID(self, id, name=None, username=None, email=None):
        try:
            account = self.session().query(Account).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            account = self.createAccount(id)
            if username:
                self.database.app.sync.submitTask(
                    sync.SyncAccountTask(username, sync.NORMAL_PRIORITY))
        if name is not None and account.name != name:
            account.name = name
        if username is not None and account.username != username:
            account.username = username
        if email is not None and account.email != email:
            account.email = email
        return account

    def getAccountByUsername(self, username):
        try:
            return self.session().query(Account).filter_by(username=username).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getSystemAccount(self):
        return self.getAccountByID(0, 'Github Code Review')

    def setOwnAccount(self, account):
        try:
            server = self.session().query(Server).one()
        except sqlalchemy.orm.exc.NoResultFound:
            server = Server()
            self.session().add(server)
            self.session().flush()
        server.own_account = account
        self.database.own_account_key = account.key

    def getOwnAccount(self):
        if self.database.own_account_key is None:
            try:
                server = self.session().query(Server).one()
            except sqlalchemy.orm.exc.NoResultFound:
                return None
            self.database.own_account_key = server.own_account.key
        try:
            return self.session().query(Account).filter_by(key=self.database.own_account_key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getLabel(self, label_id):
        try:
            return self.session().query(Label).filter_by(id=label_id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def createProject(self, *args, **kw):
        o = Project(*args, **kw)
        self.session().add(o)
        self.session().flush()
        return o

    def createAccount(self, *args, **kw):
        a = Account(*args, **kw)
        self.session().add(a)
        self.session().flush()
        return a

    def createTopic(self, *args, **kw):
        o = Topic(*args, **kw)
        self.session().add(o)
        self.session().flush()
        return o
