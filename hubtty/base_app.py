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

import datetime
import fcntl
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import warnings
import webbrowser

from urllib import parse as urlparse

import dateutil.tz

from hubtty import config
from hubtty import db
from hubtty import sync
from hubtty import search
from hubtty import requestsexceptions


class BackgroundBrowser(webbrowser.GenericBrowser):
    """Class for all browsers which are to be started in the
    background."""

    def open(self, url, new=0, autoraise=True):
        cmdline = [self.name] + [arg.replace("%s", url) for arg in self.args]
        inout = open(os.devnull, "r+")
        try:
            if sys.platform[:3] == "win":
                p = subprocess.Popen(cmdline)
            else:
                setsid = getattr(os, "setsid", None)
                if not setsid:
                    setsid = getattr(os, "setpgrp", None)
                p = subprocess.Popen(
                    cmdline,
                    close_fds=True,
                    stdin=inout,
                    stdout=inout,
                    stderr=inout,
                    preexec_fn=setsid,
                )
            return p.poll() is None
        except OSError:
            return False


class RepositoryCache:
    def __init__(self):
        self.repositories = {}

    def get(self, repository):
        if repository.key not in self.repositories:
            self.repositories[repository.key] = dict(
                unreviewed_prs=len(repository.unreviewed_prs),
                open_prs=len(repository.open_prs),
            )
        return self.repositories[repository.key]

    def clear(self, repository):
        if repository.key in self.repositories:
            del self.repositories[repository.key]


class BaseApp:
    """Non-UI base class containing shared backend logic.

    Subclasses (urwid App, Textual App) must implement the abstract
    UI-specific methods listed below.
    """

    simple_pr_search = re.compile(r"([a-zA-Z_]+/)+\d+")
    trailing_filename_re = re.compile(r".*(,[a-z]+)")

    def __init__(
        self,
        server=None,
        palette="default",
        keymap="default",
        debug=False,
        verbose=False,
        disable_sync=False,
        disable_background_sync=False,
        fetch_missing_refs=False,
        path=None,
    ):
        self.server = server
        self.config = config.Config(server, palette, keymap, path)
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING
        logging.basicConfig(
            filename=self.config.log_file,
            filemode="w",
            format="%(asctime)s %(message)s",
            level=level,
        )
        # Set the requests logger level to be less verbose, since our
        # logging output duplicates some requests logging content in places.
        req_logger = logging.getLogger("requests")
        req_logger.setLevel("WARN")
        self.log = logging.getLogger("hubtty.App")
        self.log.debug("Starting")

        self.lock_fd = open(self.config.lock_file, "w")
        try:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(
                "error: another instance of hubtty is running for: %s"
                % self.config.server["name"]
            )
            sys.exit(1)

        self.repository_cache = RepositoryCache()
        self.fetch_missing_refs = fetch_missing_refs
        self.search = search.SearchCompiler(self.getOwnAccountId)
        self.db = db.Database(self, self.config.dburi, self.search)

        self.own_account_id = None
        with self.db.getSession() as session:
            account = session.getOwnAccount()
            if account:
                self.own_account_id = account.id

        self.sync = sync.Sync(self, disable_background_sync)

        self.logged_warnings = set()

        webbrowser.register("xdg-open", None, BackgroundBrowser("xdg-open"))

    def getOwnAccountId(self):
        return self.own_account_id

    def isOwnAccount(self, account):
        return account.id == self.own_account_id

    def time(self, dt):
        utc = dt.replace(tzinfo=dateutil.tz.tzutc())
        if self.config.utc:
            return utc
        local = utc.astimezone(dateutil.tz.tzlocal())
        return local

    def parseInternalURL(self, url):
        if not url.startswith(self.config.url):
            return None
        result = urlparse.urlparse(url)
        pr = patchset = filename = None
        path = [x for x in result.path.split("/") if x]
        if path:
            pr = path[0]
        else:
            path = [x for x in result.fragment.split("/") if x]
            if path[0] == "c":
                path.pop(0)
            while path:
                if not pr:
                    pr = path.pop(0)
                    continue
                if not patchset:
                    patchset = path.pop(0)
                    continue
                if not filename:
                    filename = "/".join(path)
                    m = self.trailing_filename_re.match(filename)
                    if m:
                        filename = filename[: 0 - len(m.group(1))]
                    path = None
        return (pr, patchset, filename)

    def openInternalURL(self, result):
        (pr, patchset, filename) = result
        # TODO: support deep-linking to a filename
        self.doSearch("pr:%s" % pr)

    def _syncOnePullRequestFromQuery(self, query):
        number = prid = restid = None
        if query.startswith("pr:"):
            number = query.split(":")[1].strip()
            try:
                number = int(number)
            except ValueError:
                number = None
                prid = query.split(":")[1].strip()
        if not (number or prid):
            return
        with self.db.getSession() as session:
            if prid:
                pull_requests = session.getPullRequestsByPullRequestID(prid)
            pr_keys = [pr.key for pr in pull_requests if pr]
            restids = [pr.pr_id for pr in pull_requests if pr]
        if restids:
            for restid in restids:
                task = sync.SyncPullRequestTask(restid, sync.HIGH_PRIORITY)
                self.sync.submitTask(task)
        if not pr_keys:
            raise Exception("Pull request is not in local database.")

    def toggleHeldPullRequest(self, pr_key):
        with self.db.getSession() as session:
            pr = session.getPullRequest(pr_key)
            pr.held = not pr.held
            ret = pr.held
            if not pr.held:
                for c in pr.commits:
                    for m in pr.messages:
                        if m.pending:
                            self.sync.submitTask(
                                sync.UploadReviewTask(m.key, sync.HIGH_PRIORITY)
                            )
        self.updateStatusQueries()
        return ret

    def saveReviews(self, commit_keys, approval, message, upload, merge):
        message_keys = []
        with self.db.getSession() as session:
            account = session.getOwnAccount()
            for commit_key in commit_keys:
                k = self._saveReview(
                    session, account, commit_key, approval, message, upload, merge
                )
                if k:
                    message_keys.append(k)
        return message_keys

    def _saveReview(
        self, session, account, commit_key, approval, message, upload, merge
    ):
        message_key = None
        commit = session.getCommit(commit_key)
        pr = commit.pull_request

        existing_approval = session.getApproval(pr, account, commit.sha)
        if existing_approval:
            existing_approval.draft = True
            existing_approval.state = approval
        else:
            pr.createApproval(account, approval, commit.sha, draft=True)

        draft_message = commit.getDraftMessage()
        if not draft_message:
            if message or upload:
                draft_message = pr.createMessage(
                    commit.key,
                    None,
                    account,
                    datetime.datetime.utcnow(),
                    "",
                    draft=True,
                )
        if draft_message:
            draft_message.created = datetime.datetime.utcnow()
            draft_message.message = message
            draft_message.pending = upload
            message_key = draft_message.key
        if upload:
            pr.reviewed = True
            self.repository_cache.clear(pr.repository)
        if merge:
            sha = pr.commits[-1].sha
            pending_merge = pr.createPendingMerge(sha, "merge")
            self.sync.submitTask(
                sync.SendMergeTask(pending_merge.key, sync.HIGH_PRIORITY)
            )
        return message_key

    def startSocketListener(self):
        if os.path.exists(self.config.socket_path):
            os.unlink(self.config.socket_path)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.config.socket_path)
        self.socket.listen(1)
        self.socket_thread = threading.Thread(target=self._socketListener)
        self.socket_thread.daemon = True
        self.socket_thread.start()

    def _socketListener(self):
        while True:
            try:
                s, addr = self.socket.accept()
                self.log.debug("Accepted socket connection %s", s)
                buf = b""
                while True:
                    buf += s.recv(1)
                    if buf[-1] == 10:
                        break
                buf = buf.decode("utf8").strip()
                self.log.debug("Received %s from socket", buf)
                s.close()
                parts = buf.split()
                self.handleSocketCommand(parts[0], parts[1:])
            except Exception:
                self.log.exception("Exception in socket handler")

    def _showWarning(self, message, category, filename, lineno, file=None, line=None):
        # Don't display repeat warnings
        if str(message) in self.logged_warnings:
            return
        m = warnings.formatwarning(message, category, filename, lineno, line)
        self.log.warning(m)
        self.logged_warnings.add(str(message))
        # Log this warning, but never display it to the user; it is
        # nearly un-actionable.
        if category == requestsexceptions.InsecurePlatformWarning:
            return
        if category == requestsexceptions.SNIMissingWarning:
            return
        if category == requestsexceptions.InsecureRequestWarning:
            return
        self.showWarning(m)

    # ---- Abstract methods that UI subclasses must implement ----

    def run(self):
        """Start the UI event loop."""
        raise NotImplementedError

    def error(self, message, title="Error"):
        """Display an error to the user."""
        raise NotImplementedError

    def doSearch(self, query):
        """Execute a search query and navigate to results."""
        raise NotImplementedError

    def changeScreen(self, widget, push=True):
        """Navigate to a new screen."""
        raise NotImplementedError

    def backScreen(self, target_widget=None):
        """Navigate back to the previous screen."""
        raise NotImplementedError

    def registerPaletteEntry(self, label_id, label_color):
        """Register a color palette entry for a label."""
        raise NotImplementedError

    def openURL(self, url):
        """Open a URL in a browser."""
        raise NotImplementedError

    def updateStatusQueries(self):
        """Update held PR count in the status display."""
        raise NotImplementedError

    def handleSocketCommand(self, command, data):
        """Handle a command received via the Unix socket."""
        raise NotImplementedError

    def showWarning(self, message):
        """Display a warning to the user (from background thread)."""
        raise NotImplementedError

    def set_status(self, **kwargs):
        """Update the status display. Called from sync thread.

        Keyword arguments may include: offline, error, title, message.
        """
        raise NotImplementedError
