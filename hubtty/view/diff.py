# Copyright 2014 OpenStack Foundation
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
import logging

import urwid

from hubtty import gitrepo
from hubtty import keymap
from hubtty import mywid
from hubtty import sync
from hubtty.view import mouse_scroll_decorator


class LineContext(object):
    def __init__(self, old_file_key, new_file_key,
                 old_fn, new_fn, old_ln, new_ln,
                 header=False):
        self.old_file_key = old_file_key
        self.new_file_key = new_file_key
        self.old_fn = old_fn
        self.new_fn = new_fn
        self.old_ln = old_ln
        self.new_ln = new_ln
        self.header = header

class BaseDiffCommentEdit(urwid.Columns):
    pass

class BaseDiffComment(urwid.Columns):
    pass

class BaseDiffLine(urwid.Button):
    def selectable(self):
        return True

    def search(self, search, attribute):
        pass

class BaseFileHeader(urwid.Button):
    def selectable(self):
        return True

    def search(self, search, attribute):
        pass

class BaseFileReminder(urwid.WidgetWrap):
    pass

class DiffContextButton(urwid.WidgetWrap):
    def selectable(self):
        return True

    def __init__(self, view, diff, chunk):
        focus_map={'context-button':'focused-context-button'}
        buttons = [mywid.FixedButton(('context-button', "Expand previous 10"),
                                     on_press=self.prev),
                   mywid.FixedButton(('context-button', "Expand"),
                                     on_press=self.all),
                   mywid.FixedButton(('context-button', "Expand next 10"),
                                     on_press=self.next)]
        self._buttons = buttons
        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns([urwid.Text('')] + buttons + [urwid.Text('')],
                                dividechars=4)
        buttons = urwid.AttrMap(buttons, 'context-button')
        super(DiffContextButton, self).__init__(buttons)
        self.view = view
        self.diff = diff
        self.chunk = chunk
        self.update()

    def update(self):
        self._buttons[1].set_label("Expand %s lines of context" %
                                   (len(self.chunk.lines)),)

    def prev(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_start=10)

    def all(self, button):
        self.view.expandChunk(self.diff, self.chunk, expand_all=True)

    def next(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_end=-10)

@mouse_scroll_decorator.ScrollByWheel
class BaseDiffView(urwid.WidgetWrap, mywid.Searchable):
    def getCommands(self):
        return [
            (keymap.ACTIVATE,
             "Add an inline comment"),
            (keymap.NEXT_COMMIT,
             "Diff the next commit"),
            (keymap.PREV_COMMIT,
             "Diff the previous commit"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
            ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        ret = [(c[0], key(c[0]), c[1]) for c in commands]
        for k in self.app.config.reviewkeys.values():
            if k.get('description'):
                action = k['description']
            else:
                action = k['approval']
                if k.get('message'):
                    action = action + ": " + k.get('message')
            ret.append(('', keymap.formatKey(k['key']), action))
        return ret

    def __init__(self, app, new_commit_key):
        super(BaseDiffView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('hubtty.view.diff')
        self.app = app
        self.old_commit_key = None  # Base
        self.new_commit_key = new_commit_key
        self._init()

    def _init(self):
        del self._w.contents[:]
        self.searchInit()
        with self.app.db.getSession() as session:
            new_commit = session.getCommit(self.new_commit_key)
            old_comments = []
            new_comments = []
            self.old_file_keys = {}
            self.new_file_keys = {}
            if self.old_commit_key is not None:
                old_commit = session.getCommit(self.old_commit_key)
                self.base_sha = old_commit.sha
                for f in old_commit.files:
                    old_comments += f.comments
                    self.old_file_keys[f.path] = f.key
                show_old_commit = True
            else:
                old_commit = None
                self.base_sha = new_commit.parent
                show_old_commit = False
                # The old files are the same as the new files since we
                # are diffing from base -> change, however, we should
                # use the old file names for file lookup.
                for f in new_commit.files:
                    if f.old_path:
                        self.old_file_keys[f.old_path] = f.key
                    else:
                        self.old_file_keys[f.path] = f.key
            self.title = u'Diff of %s from %s to %s' % (
                new_commit.pull_request.repository.name,
                new_commit.parent[0:7],
                new_commit.sha[0:7])
            self.short_title = u'Diff of %s' % (new_commit.sha[0:7],)
            self.pr_key = new_commit.pull_request.key
            self.repository_name = new_commit.pull_request.repository.name
            self.sha = new_commit.sha
            for f in new_commit.files:
                new_comments += f.current_comments
                self.new_file_keys[f.path] = f.key
            comment_lists = {}
            comment_filenames = set()
            for comment in new_comments:
                path = comment.file.path
                if comment.parent:
                    if old_commit:  # we're not looking at the base
                        continue
                    key = 'old'
                    if comment.file.old_path:
                        path = comment.file.old_path
                else:
                    key = 'new'
                if comment.draft:
                    key += 'draft'
                key += '-' + str(comment.line)
                key += '-' + path
                comment_list = comment_lists.get(key, [])
                if comment.draft:
                    message = comment.message
                else:
                    message = [('comment-name', comment.author.name or comment.author.username),
                               ('comment', u': '+comment.message)]
                comment_list.append((comment.key, message))
                comment_lists[key] = comment_list
                comment_filenames.add(path)
            for comment in old_comments:
                if comment.parent:
                    continue
                path = comment.file.path
                key = 'old'
                if comment.draft:
                    key += 'draft'
                key += '-' + str(comment.line)
                key += '-' + path
                comment_list = comment_lists.get(key, [])
                if comment.draft:
                    message = comment.message
                else:
                    message = [('comment-name', comment.author.name or comment.author.username),
                               ('comment', u': '+comment.message)]
                comment_list.append((comment.key, message))
                comment_lists[key] = comment_list
                comment_filenames.add(path)
        repo = gitrepo.get_repo(self.repository_name, self.app.config)
        self._w.contents.append((self.app.header, ('pack', 1)))
        self.file_reminder = self.makeFileReminder()
        self._w.contents.append((self.file_reminder, ('pack', 1)))
        lines = []  # The initial set of lines to display
        self.file_diffs = [{}, {}]  # Mapping of fn -> DiffFile object (old, new)
        # this is a list of files:
        diffs = repo.diff(self.base_sha, self.sha,
                          show_old_commit=show_old_commit)
        for diff in diffs:
            comment_filenames.discard(diff.oldname)
            comment_filenames.discard(diff.newname)
        # There are comments referring to these files which do not
        # appear in the diff so we should create fake diff objects
        # that contain the full text.
        for filename in comment_filenames:
            diff = repo.getFile(self.base_sha, self.sha, filename)
            if diff:
                diffs.append(diff)
            else:
                self.log.debug("Unable to find file %s in commit %s" % (filename, self.sha))
        for i, diff in enumerate(diffs):
            if i > 0:
                lines.append(urwid.Text(''))
            self.file_diffs[gitrepo.OLD][diff.oldname] = diff
            self.file_diffs[gitrepo.NEW][diff.newname] = diff
            lines.extend(self.makeFileHeader(diff, comment_lists))
            for chunk in diff.chunks:
                if chunk.context:
                    if not chunk.first:
                        lines += self.makeLines(diff, chunk.lines[:10], comment_lists)
                        del chunk.lines[:10]
                    button = DiffContextButton(self, diff, chunk)
                    chunk.button = button
                    lines.append(button)
                    if not chunk.last:
                        lines += self.makeLines(diff, chunk.lines[-10:], comment_lists)
                        del chunk.lines[-10:]
                    chunk.calcRange()
                    chunk.button.update()
                    if not chunk.lines:
                        lines.remove(button)
                else:
                    lines += self.makeLines(diff, chunk.lines, comment_lists)
        listwalker = urwid.SimpleFocusListWalker(lines)
        self.listbox = urwid.ListBox(listwalker)
        self._w.contents.append((self.listbox, ('weight', 1)))
        self.old_focus = 2
        self.draft_comments = []
        self._w.set_focus(self.old_focus)
        self.handleUndisplayedComments(comment_lists)
        self.app.status.update(title=self.title)

    def handleUndisplayedComments(self, comment_lists):
        # Handle comments that landed outside our default diff context
        lastlen = 0
        while comment_lists:
            comment_lists_keys = list(comment_lists.keys())
            if len(comment_lists_keys) == lastlen:
                self.log.error("Unable to display all comments: %s" % comment_lists)
                return
            comment_lists_keys = list(comment_lists.keys())
            lastlen = len(comment_lists_keys)
            key = comment_lists_keys[0]
            kind, lineno, path = key.split('-', 2)
            lineno = int(lineno)
            if kind.startswith('old'):
                oldnew = gitrepo.OLD
            else:
                oldnew = gitrepo.NEW
            file_diffs = self.file_diffs[oldnew]
            if path not in file_diffs:
                self.log.error("Unable to display comment: %s" % key)
                del comment_lists[key]
                continue
            diff = self.file_diffs[oldnew][path]
            for chunk in diff.chunks:
                if (chunk.range[oldnew][gitrepo.START] <= lineno and
                    chunk.range[oldnew][gitrepo.END]   >= lineno):
                    i = chunk.indexOfLine(oldnew, lineno)
                    if i < (len(chunk.lines) / 2):
                        from_start = True
                    else:
                        from_start = False
                    if chunk.first and from_start:
                        from_start = False
                    if chunk.last and (not from_start):
                        from_start = True
                    if from_start:
                        self.expandChunk(diff, chunk, comment_lists, from_start=i+10)
                    else:
                        self.expandChunk(diff, chunk, comment_lists, from_end=0-(len(chunk.lines)-i)-10)
                    break

    def expandChunk(self, diff, chunk, comment_lists={}, from_start=None, from_end=None,
                    expand_all=None):
        self.log.debug("Expand chunk %s %s %s" % (chunk, from_start, from_end))
        add_lines = []
        if from_start is not None:
            index = self.listbox.body.index(chunk.button)
            add_lines = chunk.lines[:from_start]
            del chunk.lines[:from_start]
        if from_end is not None:
            index = self.listbox.body.index(chunk.button)+1
            add_lines = chunk.lines[from_end:]
            del chunk.lines[from_end:]
        if expand_all:
            index = self.listbox.body.index(chunk.button)
            add_lines = chunk.lines[:]
            del chunk.lines[:]
        if add_lines:
            lines = self.makeLines(diff, add_lines, comment_lists)
            self.listbox.body[index:index] = lines
        chunk.calcRange()
        if not chunk.lines:
            self.listbox.body.remove(chunk.button)
        else:
            chunk.button.update()

    def makeContext(self, diff, old_ln, new_ln, header=False):
        old_key = None
        new_key = None
        if not diff.old_empty:
            if diff.oldname in self.old_file_keys:
                old_key = self.old_file_keys[diff.oldname]
            elif diff.newname in self.old_file_keys:
                old_key = self.old_file_keys[diff.newname]
        if not diff.new_empty:
            new_key = self.new_file_keys.get(diff.newname)
        return LineContext(
            old_key, new_key,
            diff.oldname, diff.newname,
            old_ln, new_ln, header)

    def makeLines(self, diff, lines_to_add, comment_lists):
        raise NotImplementedError

    def makeFileHeader(self, diff, comment_lists):
        raise NotImplementedError

    def makeFileReminder(self):
        raise NotImplementedError

    def interested(self, event):
        if not ((isinstance(event, sync.PullRequestAddedEvent) and
                 self.pr_key in event.related_pr_keys)
                or
                (isinstance(event, sync.PullRequestUpdatedEvent) and
                 self.pr_key in event.related_pr_keys)):
            #self.log.debug("Ignoring refresh diff due to event %s" % (event,))
            return False
        #self.log.debug("Refreshing diff due to event %s" % (event,))
        return True

    def refresh(self, event=None):
        #TODO
        pass

    def getContextAtTop(self, size):
        middle, top, bottom = self.listbox.calculate_visible(size, True)
        if top and top[1]:
            (widget, pos, rows) = top[1][-1]
        elif middle:
            pos = middle[2]
        # Make sure the first header shows up as soon as it scrolls up
        if pos > 1:
            pos -= 1
        context = None
        while True:
            item = self.listbox.body[pos]
            if hasattr(item, 'context'):
                break
            pos -= 1
        if pos > 0:
            context = item.context
        return context

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        old_focus = self.listbox.focus
        if not self.app.input_buffer:
            key = super(BaseDiffView, self).keypress(size, key)
        new_focus = self.listbox.focus
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)

        context = self.getContextAtTop(size)
        if context:
            self.file_reminder.set(context.old_fn,
                                   context.new_fn)
        else:
            self.file_reminder.set('', '')

        if (isinstance(old_focus, BaseDiffCommentEdit) and
            (old_focus != new_focus or (keymap.PREV_SCREEN in commands))):
            self.cleanupEdit(old_focus)
        if keymap.NEXT_COMMIT in commands:
            self.moveCommit(1)
            return None
        if keymap.PREV_COMMIT in commands:
            self.moveCommit(-1)
            return None
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return None
        if key in self.app.config.reviewkeys:
            self.reviewKey(self.app.config.reviewkeys[key])
            return None
        return key

    def mouse_event(self, size, event, button, x, y, focus):
        old_focus = self.listbox.focus
        r = super(BaseDiffView, self).mouse_event(size, event, button, x, y, focus)
        new_focus = self.listbox.focus
        if old_focus != new_focus and isinstance(old_focus, BaseDiffCommentEdit):
            self.cleanupEdit(old_focus)
        return r

    def makeCommentEdit(self, edit):
        raise NotImplementedError

    def onSelect(self, button):
        pos = self.listbox.focus_position
        e = self.makeCommentEdit(self.listbox.body[pos])
        self.listbox.body.insert(pos+1, e)
        self.listbox.focus_position = pos+1

    def cleanupEdit(self, edit):
        raise NotImplementedError

    def deleteComment(self, comment_key):
        with self.app.db.getSession() as session:
            comment = session.getComment(comment_key)
            session.delete(comment)

    def saveComment(self, context, text, new=True):
        if not new:
            parent = True
        else:
            parent = False
        if new:
            line_num = context.new_ln
            file_key = context.new_file_key
        else:
            line_num = context.old_ln
            file_key = context.old_file_key
        if file_key is None:
            raise Exception("Comment is not associated with a file")
        with self.app.db.getSession() as session:
            account = session.getOwnAccount()
            pr = session.getPullRequest(self.pr_key)
            latest_pr_commit = pr.commits[-1]
            commit = session.getCommit(self.new_commit_key)

            message = latest_pr_commit.getDraftMessage()
            if not message:
                message = pr.createMessage(latest_pr_commit.key, None, account,
                                           datetime.datetime.utcnow(),
                                           '', draft=True)
            comment = message.createComment(file_key, None, account, None,
                                            datetime.datetime.utcnow(),
                                            datetime.datetime.utcnow(),
                                            parent, commit.sha, commit.sha,
                                            line_num, line_num, text, draft=True)
            key = comment.key
        return key

    def reviewKey(self, reviewkey):
        pr_view = self.app.getPreviousScreen()
        if pr_view:
            pr_view.reviewKey(reviewkey)
        self.app.backScreen()

    def moveCommit(self, offset):
        commits = []
        commit_idx = None
        with self.app.db.getSession() as session:
            pr = session.getPullRequest(self.pr_key)
            for c in pr.commits:
                commits.append(c.key)

        for i, key in enumerate(commits):
            if key == self.new_commit_key:
                commit_idx = i + offset
                break
        if commit_idx >= len(commits):
            return
        if commit_idx < 0:
            return
        self.new_commit_key = commits[commit_idx]
        self._init()
