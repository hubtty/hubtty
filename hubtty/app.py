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

import argparse
import colorsys
import datetime
import dateutil
import fcntl
import functools
import logging
import os
import re
import socket
import subprocess
import sys
import textwrap
import threading
import warnings
import webbrowser

import six
from six.moves import queue
from six.moves.urllib import parse as urlparse
import sqlalchemy.exc
import urwid

from hubtty import db
from hubtty import config
from hubtty import gitrepo
from hubtty import keymap
from hubtty import mywid
from hubtty import palette
from hubtty import sync
from hubtty import search
from hubtty import requestsexceptions
from hubtty.view import pull_request_list as view_pr_list
from hubtty.view import repository_list as view_repository_list
from hubtty.view import pull_request as view_pr
import hubtty.view
import hubtty.version

WELCOME_TEXT = """\
Welcome to Hubtty!

To get started, you should subscribe to some repositories.  Press the "L" key (shift-L) to list all the repositories the user has explicit permission on, navigate to the ones you are interested in, and then press "s" to subscribe to them.  Use the `additional-repositories` setting to add more repositories to this list.

Hubtty will automatically clone the repositories and sync pull requests in your subscribed repositories. Repositories are cloned in ~/hubtty by default.

Change your configuration in %s.

Press the F1 key anywhere to get help.  Your terminal emulator may require you to press function-F1 or alt-F1 instead.

""" % config.CONFIG_PATH

class StatusHeader(urwid.WidgetWrap):
    def __init__(self, app):
        super(StatusHeader, self).__init__(urwid.Columns([]))
        self.app = app
        self.title_widget = urwid.Text(u'Start')
        self.error_widget = urwid.Text('')
        self.offline_widget = urwid.Text('')
        self.sync_widget = urwid.Text(u'Sync: 0')
        self.held_widget = urwid.Text(u'')
        self._w.contents.append((self.title_widget, ('pack', None, False)))
        self._w.contents.append((urwid.Text(u''), ('weight', 1, False)))
        self._w.contents.append((self.held_widget, ('pack', None, False)))
        self._w.contents.append((self.error_widget, ('pack', None, False)))
        self._w.contents.append((self.offline_widget, ('pack', None, False)))
        self._w.contents.append((self.sync_widget, ('pack', None, False)))
        self.error = None
        self.offline = None
        self.title = None
        self.message = None
        self.sync = None
        self.held = None
        self._error = False
        self._offline = False
        self._title = ''
        self._message = ''
        self._sync = 0
        self._held = 0
        self.held_key = self.app.config.keymap.formatKeys(keymap.LIST_HELD)

    def update(self, title=None, message=None, error=None,
               offline=None, refresh=True, held=None):
        if title is not None:
            self.title = title
        if message is not None:
            self.message = message
        if error is not None:
            self.error = error
        if offline is not None:
            self.offline = offline
        if held is not None:
            self.held = held
        self.sync = self.app.sync.queue.qsize()
        if refresh:
            self.refresh()

    def refresh(self):
        if (self._title != self.title or self._message != self.message):
            self._title = self.title
            self._message = self.message
            t = self.message or self.title
            self.title_widget.set_text(t)
        if self._held != self.held:
            self._held = self.held
            if self._held:
                self.held_widget.set_text(('error', u'Held: %s (%s)' % (self._held, self.held_key)))
            else:
                self.held_widget.set_text(u'')
        if self._error != self.error:
            self._error = self.error
            if self._error:
                self.error_widget.set_text(('error', u' Error'))
            else:
                self.error_widget.set_text(u'')
        if self._offline != self.offline:
            self._offline = self.offline
            if self._offline:
                self.offline_widget.set_text(u' Offline')
            else:
                self.offline_widget.set_text(u'')
        if self._sync != self.sync:
            self._sync = self.sync
            self.sync_widget.set_text(u' Sync: %i' % self._sync)


class BreadCrumbBar(urwid.WidgetWrap):
    BREADCRUMB_SYMBOL = u'\N{BLACK RIGHT-POINTING SMALL TRIANGLE}'
    BREADCRUMB_WIDTH = 25

    def __init__(self):
        self.prefix_text = urwid.Text(u' \N{WATCH}  ')
        self.breadcrumbs = urwid.Columns([], dividechars=3)
        self.display_widget = urwid.Columns(
            [('pack', self.prefix_text), self.breadcrumbs])
        super(BreadCrumbBar, self).__init__(self.display_widget)

    def _get_breadcrumb_text(self, screen):
        title = getattr(screen, 'short_title', None)
        if not title:
            title = getattr(screen, 'title', str(screen))
        text = "%s %s" % (BreadCrumbBar.BREADCRUMB_SYMBOL, title)
        if len(text) > 23:
            text = "%s..." % text[:20]
        return urwid.Text(text, wrap='clip')

    def _get_breadcrumb_column_options(self):
        return self.breadcrumbs.options("given", BreadCrumbBar.BREADCRUMB_WIDTH)

    def _update(self, screens):
        breadcrumb_contents = []
        for screen in screens:
            breadcrumb_contents.append((
                self._get_breadcrumb_text(screen),
                self._get_breadcrumb_column_options()))
        self.breadcrumbs.contents = breadcrumb_contents
        # Update focus so we always have the right end of the breadcrumb trail
        # in view. Urwid will gracefully handle clipping from the left when
        # there is overflow.as trail grows, shrinks, or screen is resized.
        if len(self.breadcrumbs.contents):
            self.breadcrumbs.focus_position = len(self.breadcrumbs.contents) - 1


class SearchDialog(mywid.ButtonDialog):
    signals = ['search', 'cancel']
    def __init__(self, app, default):
        self.app = app
        search_button = mywid.FixedButton('Search')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(search_button, 'click',
                             lambda button:self._emit('search'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        super(SearchDialog, self).__init__("Search",
                                           "Enter a pull request or search string.",
                                           entry_prompt="Search: ",
                                           entry_text=default,
                                           buttons=[search_button,
                                                    cancel_button],
                                           ring=app.ring)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(SearchDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.ACTIVATE in commands:
            self._emit('search')
            return None
        return key

# From: cpython/file/2.7/Lib/webbrowser.py with modification to
# redirect stdin/out/err.
class BackgroundBrowser(webbrowser.GenericBrowser):
    """Class for all browsers which are to be started in the
       background."""

    def open(self, url, new=0, autoraise=True):
        cmdline = [self.name] + [arg.replace("%s", url)
                                 for arg in self.args]
        inout = open(os.devnull, "r+")
        try:
            if sys.platform[:3] == 'win':
                p = subprocess.Popen(cmdline)
            else:
                setsid = getattr(os, 'setsid', None)
                if not setsid:
                    setsid = getattr(os, 'setpgrp', None)
                p = subprocess.Popen(cmdline, close_fds=True,
                                     stdin=inout, stdout=inout,
                                     stderr=inout, preexec_fn=setsid)
            return (p.poll() is None)
        except OSError:
            return False

class RepositoryCache(object):
    def __init__(self):
        self.repositories = {}

    def get(self, repository):
        if repository.key not in self.repositories:
            self.repositories[repository.key] = dict(
                unreviewed_prs = len(repository.unreviewed_prs),
                open_prs = len(repository.open_prs),
            )
        return self.repositories[repository.key]

    def clear(self, repository):
        if repository.key in self.repositories:
            del self.repositories[repository.key]

class App(object):
    simple_pr_search = re.compile(r'([a-zA-Z_]+/)+\d+')

    def __init__(self, server=None, palette='default',
                 keymap='default', debug=False, verbose=False,
                 disable_sync=False, disable_background_sync=False,
                 fetch_missing_refs=False,
                 path=None):
        self.server = server
        self.config = config.Config(server, palette, keymap, path)
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING
        logging.basicConfig(filename=self.config.log_file, filemode='w',
                            format='%(asctime)s %(message)s',
                            level=level)
        # Python2.6 Logger.setLevel doesn't convert string name
        # to integer code. Here, we set the requests logger level to
        # be less verbose, since our logging output duplicates some
        # requests logging content in places.
        req_level_name = 'WARN'
        req_logger = logging.getLogger('requests')
        if sys.version_info < (2, 7):
            level = logging.getLevelName(req_level_name)
            req_logger.setLevel(level)
        else:
            req_logger.setLevel(req_level_name)
        self.log = logging.getLogger('hubtty.App')
        self.log.debug("Starting")

        self.lock_fd = open(self.config.lock_file, 'w')
        try:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print("error: another instance of hubtty is running for: %s" % self.config.server['name'])
            sys.exit(1)

        self.repository_cache = RepositoryCache()
        self.ring = mywid.KillRing()
        self.input_buffer = []
        webbrowser.register('xdg-open', None, BackgroundBrowser("xdg-open"))

        self.fetch_missing_refs = fetch_missing_refs
        self.config.keymap.updateCommandMap()
        self.search = search.SearchCompiler(self.getOwnAccountId)
        self.db = db.Database(self, self.config.dburi, self.search)

        self.own_account_id = None
        with self.db.getSession() as session:
            account = session.getOwnAccount()
            if account:
                self.own_account_id = account.id

        self.sync = sync.Sync(self, disable_background_sync)

        self.status = StatusHeader(self)
        self.header = urwid.AttrMap(self.status, 'header')
        self.screens = urwid.MonitoredList()
        self.breadcrumbs = BreadCrumbBar()
        self.screens.set_modified_callback(
            functools.partial(self.breadcrumbs._update, self.screens))
        if self.config.breadcrumbs:
            self.footer = urwid.AttrMap(self.breadcrumbs, 'footer')
        else:
            self.footer = None
        screen = view_repository_list.RepositoryListView(self)
        self.status.update(title=screen.title)
        self.updateStatusQueries()
        self.frame = urwid.Frame(body=screen, footer=self.footer)
        self.loop = urwid.MainLoop(self.frame, palette=self.config.palette.getPalette(),
                                   handle_mouse=self.config.handle_mouse,
                                   unhandled_input=self.unhandledInput,
                                   input_filter=self.inputFilter)

        self.sync_pipe = self.loop.watch_pipe(self.refresh)
        self.error_queue = queue.Queue()
        self.error_pipe = self.loop.watch_pipe(self._errorPipeInput)
        self.logged_warnings = set()
        self.command_pipe = self.loop.watch_pipe(self._commandPipeInput)
        self.command_queue = queue.Queue()

        warnings.showwarning = self._showWarning

        has_subscribed_repositories = False
        with self.db.getSession() as session:
            if session.getRepositories(subscribed=True):
                has_subscribed_repositories = True
        if not has_subscribed_repositories:
            self.welcome()

        self.loop.screen.tty_signal_keys(start='undefined', stop='undefined')
        if os.environ.get('COLORTERM') == 'truecolor':
            self.loop.screen.set_terminal_properties(colors=2**24)
        with self.db.getSession() as session:
            for label in session.getLabels():
                self.registerPaletteEntry(label.id, label.color)

        self.startSocketListener()

        if not disable_sync:
            self.sync_thread = threading.Thread(target=self.sync.run, args=(self.sync_pipe,))
            self.sync_thread.daemon = True
            self.sync_thread.start()
        else:
            self.sync_thread = None
            self.sync.offline = True
            self.status.update(offline=True)

    def registerPaletteEntry(self, label_id, label_color):
        name = "label_" + str(label_id)
        color = "#" + str(label_color)
        # Get the luminance of the color. We convert hex to RGB, then RGB to HLS.
        r,g,b = tuple(int(label_color[i:i+2], 16) for i in (0, 2, 4))
        _,l,_ = colorsys.rgb_to_hls(r, g, b)
        if l > 110:
            fg = "#111"
        else:
            fg = "#eee"
        default_fg, default_bg = self.config.palette.getPaletteItem('pr-data')
        self.loop.screen.register_palette_entry(name, default_fg, default_bg, foreground_high=fg, background_high=color)

    def getOwnAccountId(self):
        return self.own_account_id

    def isOwnAccount(self, account):
        return account.id == self.own_account_id

    def run(self):
        try:
            self.loop.run()
        except KeyboardInterrupt:
            pass

    def _quit(self, widget=None):
        raise urwid.ExitMainLoop()

    def quit(self):
        dialog = mywid.YesNoDialog(u'Quit',
                                   u'Are you sure you want to quit?')
        urwid.connect_signal(dialog, 'no', self.backScreen)
        urwid.connect_signal(dialog, 'yes', self._quit)

        self.popup(dialog)

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
                self.log.debug("Accepted socket connection %s" % (s,))
                buf = b''
                while True:
                    buf += s.recv(1)
                    if buf[-1] == 10:
                        break
                buf = buf.decode('utf8').strip()
                self.log.debug("Received %s from socket" % (buf,))
                s.close()
                parts = buf.split()
                self.command_queue.put((parts[0], parts[1:]))
                os.write(self.command_pipe, six.b('command\n'))
            except Exception:
                self.log.exception("Exception in socket handler")

    def clearInputBuffer(self):
        if self.input_buffer:
            self.input_buffer = []
            self.status.update(message='')

    def changeScreen(self, widget, push=True):
        self.log.debug("Changing screen to %s" % (widget,))
        self.status.update(error=False, title=widget.title)
        if push:
            self.screens.append(self.frame.body)
        self.clearInputBuffer()
        self.frame.body = widget

    def getPreviousScreen(self):
        if not self.screens:
            return None
        return self.screens[-1]

    def backScreen(self, target_widget=None):
        if not self.screens:
            return
        while self.screens:
            widget = self.screens.pop()
            if (not target_widget) or (widget is target_widget):
                break
        self.log.debug("Popping screen to %s" % (widget,))
        if hasattr(widget, 'title'):
            self.status.update(title=widget.title)
        self.clearInputBuffer()
        self.frame.body = widget
        self.refresh(force=True)

    def findPullRequestList(self):
        for widget in reversed(self.screens):
            if isinstance(widget, view_pr_list.PullRequestListView):
                return widget
        return None

    def clearHistory(self):
        self.log.debug("Clearing screen history")
        while self.screens:
            widget = self.screens.pop()
            self.clearInputBuffer()
            self.frame.body = widget

    def refresh(self, data=None, force=False):
        widget = self.frame.body
        while isinstance(widget, urwid.Overlay):
            widget = widget.contents[0][0]
        interested = force
        invalidate = False
        try:
            while True:
                event = self.sync.result_queue.get(0)
                if widget.interested(event):
                    interested = True
                if hasattr(event, 'held_changed') and event.held_changed:
                    invalidate = True
        except queue.Empty:
            pass
        if interested:
            widget.refresh()
        if invalidate:
            self.updateStatusQueries()
        self.status.refresh()

    def updateStatusQueries(self):
        with self.db.getSession() as session:
            held = len(session.getHeld())
            self.status.update(held=held)

    def popup(self, widget,
              relative_width=50, relative_height=25,
              min_width=20, min_height=8,
              width=None, height=None):
        self.clearInputBuffer()
        if width is None:
            width = ('relative', relative_width)
        if height is None:
            height = ('relative', relative_height)
        overlay = urwid.Overlay(widget, self.frame.body,
                                'center', width,
                                'middle', height,
                                min_width=min_width, min_height=min_height)
        if hasattr(widget, 'title'):
            overlay.title = widget.title
        self.log.debug("Overlaying %s on screen %s" % (widget, self.frame.body))
        self.screens.append(self.frame.body)
        self.frame.body = overlay

    def getGlobalCommands(self):
        return list(mywid.GLOBAL_HELP)

    def getGlobalHelp(self):
        keys =  [(k, self.config.keymap.formatKeys(k), t) for (k, t) in self.getGlobalCommands()]
        for d in self.config.dashboards.values():
            keys.append(('', d['key'], d['name']))
        return keys

    def help(self):
        if not hasattr(self.frame.body, 'help'):
            return
        global_help = self.getGlobalHelp()
        parts = [('Global Keys', global_help),
                 ('This Screen', self.frame.body.help())]
        keylen = 0
        for title, items in parts:
            for cmd, keys, text in items:
                keylen = max(len(keys), keylen)
        text = ''
        for title, items in parts:
            if text:
                text += '\n'
            text += title+'\n'
            text += '%s\n' % ('='*len(title),)
            for cmd, keys, cmdtext in items:
                text += '{keys:{width}} {text}\n'.format(
                    keys=keys, width=keylen, text=cmdtext)
        dialog = mywid.MessageDialog('Help for %s' % version(), text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def welcome(self):
        text = WELCOME_TEXT
        dialog = mywid.MessageDialog('Welcome', text)
        lines = text.split('\n')
        total_lines = 0
        for line in lines:
            total_lines = total_lines + 1 + int(len(line)/76)
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=total_lines+4)

    def _syncOnePullRequestFromQuery(self, query):
        number = prid = restid = None
        if query.startswith("pr:"):
            number = query.split(':')[1].strip()
            try:
                number = int(number)
            except ValueError:
                number = None
                prid = query.split(':')[1].strip()
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
            raise Exception('Pull request is not in local database.')

    def doSearch(self, query):
        self.log.debug("Search query: %s" % query)
        try:
            self._syncOnePullRequestFromQuery(query)
        except Exception as e:
            return self.error(str(e))
        with self.db.getSession() as session:
            try:
                pull_requests = session.getPullRequests(query)
            except hubtty.search.SearchSyntaxError as e:
                return self.error(e.message)
            except sqlalchemy.exc.OperationalError as e:
                return self.error(e.message)
            except Exception as e:
                return self.error(str(e))
            pr_key = None
            if len(pull_requests) == 1:
                pr_key = pull_requests[0].key
        try:
            if pr_key:
                view = view_pr.PullRequestView(self, pr_key)
            else:
                view = view_pr_list.PullRequestListView(self, query)
            self.changeScreen(view)
        except hubtty.view.DisplayError as e:
            return self.error(e.message)

    def searchDialog(self, default):
        dialog = SearchDialog(self, default)
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.backScreen())
        urwid.connect_signal(dialog, 'search',
            lambda button: self._searchDialog(dialog))
        self.popup(dialog, min_width=76, min_height=8)

    def _searchDialog(self, dialog):
        self.backScreen()
        query = dialog.entry.edit_text.strip()
        if self.simple_pr_search.match(query):
            query = 'pr:%s' % query
        else:
            result = self.parseInternalURL(query)
            if result is not None:
                return self.openInternalURL(result)
        self.doSearch(query)

    trailing_filename_re = re.compile('.*(,[a-z]+)')
    def parseInternalURL(self, url):
        if not url.startswith(self.config.url):
            return None
        result = urlparse.urlparse(url)
        pr = patchset = filename = None
        path = [x for x in result.path.split('/') if x]
        if path:
            pr = path[0]
        else:
            path = [x for x in result.fragment.split('/') if x]
            if path[0] == 'c':
                path.pop(0)
            while path:
                if not pr:
                    pr = path.pop(0)
                    continue
                if not patchset:
                    patchset = path.pop(0)
                    continue
                if not filename:
                    filename = '/'.join(path)
                    m = self.trailing_filename_re.match(filename)
                    if m:
                        filename = filename[:0-len(m.group(1))]
                    path = None
        return (pr, patchset, filename)

    def openInternalURL(self, result):
        (pr, patchset, filename) = result
        # TODO: support deep-linking to a filename
        self.doSearch('pr:%s' % pr)

    def error(self, message, title='Error'):
        dialog = mywid.MessageDialog(title, message)
        urwid.connect_signal(dialog, 'close',
                             lambda button: self.backScreen())

        cols, rows = self.loop.screen.get_cols_rows()
        cols = int(cols*.5)
        lines = textwrap.wrap(message, cols)
        min_height = max(4, len(lines)+4)

        self.popup(dialog, min_height=min_height)
        return None

    def inputFilter(self, keys, raw):
        if 'window resize' in keys:
            m = getattr(self.frame.body, 'onResize', None)
            if m:
                m()
        return keys

    def unhandledInput(self, key):
        # get commands from buffer
        keys = self.input_buffer + [key]
        commands = self.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self.backScreen()
        elif keymap.TOP_SCREEN in commands:
            self.clearHistory()
            self.refresh(force=True)
        elif keymap.HELP in commands:
            self.help()
        elif keymap.QUIT in commands:
            self.quit()
        elif keymap.PR_SEARCH in commands:
            self.searchDialog('')
        elif keymap.LIST_HELD in commands:
            self.doSearch("is:held")
        elif key in self.config.dashboards:
            d = self.config.dashboards[key]
            view = view_pr_list.PullRequestListView(self, d['query'], d['name'],
                                                    sort_by=d.get('sort-by'),
                                                    reverse=d.get('reverse'))
            self.changeScreen(view)
        elif keymap.FURTHER_INPUT in commands:
            self.input_buffer.append(key)
            msg = ''.join(self.input_buffer)
            commands = dict(self.getGlobalCommands())
            if hasattr(self.frame.body, 'getCommands'):
                commands.update(dict(self.frame.body.getCommands()))
            further_commands = self.config.keymap.getFurtherCommands(keys)
            completions = []
            for (key, cmds) in further_commands:
                for cmd in cmds:
                    if cmd in commands:
                        completions.append(key)
            completions = ' '.join(completions)
            msg = '%s: %s' % (msg, completions)
            self.status.update(message=msg)
            return
        self.clearInputBuffer()

    def openURL(self, url):
        self.log.debug("Open URL %s" % url)
        webbrowser.open_new_tab(url)
        self.loop.screen.clear()

    def time(self, dt):
        utc = dt.replace(tzinfo=dateutil.tz.tzutc())
        if self.config.utc:
            return utc
        local = utc.astimezone(dateutil.tz.tzlocal())
        return local

    def _errorPipeInput(self, data=None):
        (title, message) = self.error_queue.get()
        self.error(message, title=title)

    def _showWarning(self, message, category, filename, lineno,
                     file=None, line=None):
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
        self.error_queue.put(('Warning', m))
        os.write(self.error_pipe, six.b('error\n'))

    def _commandPipeInput(self, data=None):
        (command, data) = self.command_queue.get()
        if command == 'open':
            url = data[0]
            self.log.debug("Opening URL %s" % (url,))
            result = self.parseInternalURL(url)
            if result is not None:
                self.openInternalURL(result)
        else:
            self.log.error("Unable to parse command %s with data %s" % (command, data))

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
                                sync.UploadReviewTask(m.key, sync.HIGH_PRIORITY))
        self.updateStatusQueries()
        return ret

    def localCheckoutCommit(self, repository_name, commit_sha):
        repo = gitrepo.get_repo(repository_name, self.config)
        try:
            repo.checkout(commit_sha)
            dialog = mywid.MessageDialog('Checkout', 'Pull request checked out in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_height=min_height)

    def localCherryPickCommit(self, repository_name, commit_sha):
        repo = gitrepo.get_repo(repository_name, self.config)
        try:
            repo.cherryPick(commit_sha)
            dialog = mywid.MessageDialog('Cherry-Pick', 'Pull request cherry-picked in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_height=min_height)

    def saveReviews(self, commit_keys, approval, message, upload, merge):
        message_keys = []
        with self.db.getSession() as session:
            account = session.getOwnAccount()
            for commit_key in commit_keys:
                k = self._saveReview(session, account, commit_key,
                                     approval, message, upload, merge)
                if k:
                    message_keys.append(k)
        return message_keys

    def _saveReview(self, session, account, commit_key,
                    approval, message, upload, merge):
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
                draft_message = pr.createMessage(commit.key, None, account,
                                                 datetime.datetime.utcnow(),
                                                 '', draft=True)
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
            pending_merge = pr.createPendingMerge(sha,'merge')
            self.sync.submitTask(
                    sync.SendMergeTask(pending_merge.key, sync.HIGH_PRIORITY))
        return message_key



def version():
    return "Hubtty version: %s" % hubtty.version.version_info.release_string()

class PrintKeymapAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for cmd in sorted(keymap.DEFAULT_KEYMAP.keys()):
            print(cmd.replace(' ', '-'))
        sys.exit(0)

class PrintPaletteAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for attr in sorted(palette.DEFAULT_PALETTE.keys()):
            print(attr)
        sys.exit(0)

class OpenPullRequestAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        cf = config.Config(namespace.server, namespace.palette,
                           namespace.keymap, namespace.path)
        url = values[0]
        if not url.startswith(cf.url):
            print('Supplied URL must start with %s' % (cf.url,))
            sys.exit(1)

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(cf.socket_path)
        s.sendall(('open %s\n' % url).encode('utf8'))
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description='Console client for Github Code Review.')
    parser.add_argument('-c', dest='path',
                        help='path to config file')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='enable more verbose logging')
    parser.add_argument('-d', dest='debug', action='store_true',
                        help='enable debug logging')
    parser.add_argument('--no-sync', dest='no_sync', action='store_true',
                        help='disable remote syncing')
    parser.add_argument('--debug-sync', dest='debug_sync', action='store_true',
                        help='disable most background sync tasks for debugging')
    parser.add_argument('--fetch-missing-refs', dest='fetch_missing_refs',
                        action='store_true',
                        help='fetch any refs missing from local repos')
    parser.add_argument('--print-keymap', nargs=0, action=PrintKeymapAction,
                        help='print the keymap command names to stdout')
    parser.add_argument('--print-palette', nargs=0, action=PrintPaletteAction,
                        help='print the palette attribute names to stdout')
    parser.add_argument('--open', nargs=1, action=OpenPullRequestAction,
                        metavar='URL',
                        help='open the given URL in a running Hubtty')
    parser.add_argument('--version', dest='version', action='version',
                        version=version(),
                        help='show Hubtty\'s version')
    parser.add_argument('-p', dest='palette', default='default',
                        help='color palette to use')
    parser.add_argument('-k', dest='keymap', default='default',
                        help='keymap to use')
    parser.add_argument('server', nargs='?',
                        help='the server to use (as specified in config file)')
    args = parser.parse_args()
    g = App(args.server, args.palette, args.keymap, args.debug, args.verbose,
            args.no_sync, args.debug_sync, args.fetch_missing_refs, args.path)
    g.run()


if __name__ == '__main__':
    main()
