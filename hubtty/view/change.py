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
import datetime
import logging
try:
    import ordereddict
except:
    pass
import textwrap

import urwid

from hubtty import gitrepo
from hubtty import keymap
from hubtty import mywid
from hubtty import sync
from hubtty.view import side_diff as view_side_diff
from hubtty.view import unified_diff as view_unified_diff
from hubtty.view import mouse_scroll_decorator
import hubtty.view

try:
    OrderedDict = collections.OrderedDict
except AttributeError:
    OrderedDict = ordereddict.OrderedDict

class EditLabelsDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['save', 'cancel']
    def __init__(self, app, change):
        self.app = app
        save_button = mywid.FixedButton('Save')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(save_button, 'click',
                             lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))

        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        self.labels_checkboxes = []

        rows.append(urwid.Text(u"Labels:"))
        for label in change.project.labels:
            b = mywid.FixedCheckBox(label.name, state=(label in change.labels))
            rows.append(b)
            self.labels_checkboxes.append(b)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(EditLabelsDialog, self).__init__(urwid.LineBox(fill,
                                                             'Set pull request labels'))

class ReviewDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['merge', 'save', 'cancel']
    def __init__(self, app, commit_key, message=''):
        self.commit_key = commit_key
        self.app = app
        save_button = mywid.FixedButton(u'Save')
        merge_button = mywid.FixedButton(u'Save and Merge')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(merge_button, 'click',
            lambda button:self._emit('merge'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        rows = []
        review_states = {
            'REQUEST_CHANGES': 'Request Changes',
            'COMMENT': 'Comment',
            'APPROVE': 'Approve'
        }
        self.button_group = []
        with self.app.db.getSession() as session:
            commit = session.getCommit(self.commit_key)
            change = commit.change
            buttons = [('pack', save_button)]
            if commit.change.canMerge():
                buttons.append(('pack', merge_button))
            buttons.append(('pack', cancel_button))
            buttons = urwid.Columns(buttons, dividechars=2)
            if commit == change.commits[-1]:
                current = None
                for approval in change.approvals:
                    if self.app.isOwnAccount(approval.reviewer):
                        current = approval.state
                        break
                if current is None:
                    current = 'COMMENT'

                rows.append(urwid.Text('Review changes:'))
                for state in review_states:
                    b = urwid.RadioButton(self.button_group, review_states[state], state=(state == current))
                    b._value = state
                    if state == 'APPROVE':
                        b = urwid.AttrMap(b, 'positive-label')
                    elif state == 'REQUEST_CHANGES':
                        b = urwid.AttrMap(b, 'negative-label')
                    rows.append(b)
                rows.append(urwid.Divider())
            m = commit.getPendingMessage()
            if not m:
                m = commit.getDraftMessage()
            if m:
                message = m.message
        self.message = mywid.MyEdit(u"Message: \n", edit_text=message,
                                    multiline=True, ring=app.ring)
        rows.append(self.message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(ReviewDialog, self).__init__(urwid.LineBox(fill, 'Review'))

    def getValues(self):
        approval = ''
        for button in self.button_group:
            if button.state:
                approval = button._value
        message = self.message.edit_text.strip()
        return (approval, message)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ReviewDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self._emit('cancel')
            return None
        return key

class MergeDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['merge', 'cancel']
    def __init__(self, app, change, title='', message=''):
        self.app = app
        merge_button = mywid.FixedButton(u'Merge')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(merge_button, 'click',
            lambda button:self._emit('merge'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        rows = []
        merge_method = {
            'merge': 'Create a merge commit',
            'squash': 'Squash and merge',
            'rebase': 'Rebase and merge'
        }
        self.button_group = []
        buttons = []
        if change.canMerge():
            buttons.append(('pack', merge_button))
        buttons.append(('pack', cancel_button))
        buttons = urwid.Columns(buttons, dividechars=2)
        default = 'merge'
        rows.append(urwid.Text('Merge method:'))
        for method in merge_method:
            b = urwid.RadioButton(self.button_group, merge_method[method], state=(method == default))
            b._value = method
            rows.append(b)
        rows.append(urwid.Divider())
        self.commit_title = mywid.MyEdit(u"Commit title (Optional): \n", edit_text=title,
                                    multiline=False, ring=app.ring)
        rows.append(self.commit_title)
        self.commit_message = mywid.MyEdit(u"Commit message (Optional): \n", edit_text=message,
                                    multiline=True, ring=app.ring)
        rows.append(self.commit_message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(MergeDialog, self).__init__(urwid.LineBox(fill, 'Merge Change'))

    def getValues(self):
        strategy = ''
        for button in self.button_group:
            if button.state:
                strategy = button._value
        title = self.commit_title.edit_text.strip()
        if title == '':
            title = None
        message = self.commit_message.edit_text.strip()
        if message == '':
            message = None
        return (strategy, title, message)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(MergeDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self._emit('cancel')
            return None
        return key

class EditPullRequestDialog(urwid.WidgetWrap, mywid.LineBoxTitlePropertyMixin):
    signals = ['save', 'cancel']
    def __init__(self, app, change):
        self.app = app
        save_button = mywid.FixedButton(u'Save')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []

        self.pr_title = mywid.MyEdit(edit_text=change.title, multiline=False,
                ring=app.ring)
        rows.append(urwid.Text(u"Title:"))
        rows.append(self.pr_title)
        rows.append(urwid.Divider())
        self.pr_description = mywid.MyEdit(edit_text=change.body,
                multiline=True, ring=app.ring)
        rows.append(urwid.Text(u"Description:"))
        rows.append(self.pr_description)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(EditPullRequestDialog, self).__init__(urwid.LineBox(fill, 'Edit Pull Request'))

class ReviewButton(mywid.FixedButton):
    def __init__(self, commit_row):
        super(ReviewButton, self).__init__(('commit-button', u'Review'))
        self.commit_row = commit_row
        self.change_view = commit_row.change_view
        urwid.connect_signal(self, 'click',
            lambda button: self.openReview())

    def openReview(self, message=''):
        self.dialog = ReviewDialog(self.change_view.app,
                                   self.commit_row.commit_key,
                                   message=message)
        urwid.connect_signal(self.dialog, 'save',
            lambda button: self.closeReview(True, False))
        urwid.connect_signal(self.dialog, 'merge',
            lambda button: self.closeReview(True, True))
        urwid.connect_signal(self.dialog, 'cancel',
            lambda button: self.closeReview(False, False))
        self.change_view.app.popup(self.dialog,
                                   relative_width=50, relative_height=75,
                                   min_width=60, min_height=20)

    def closeReview(self, upload, merge):
        approval, message = self.dialog.getValues()
        self.change_view.saveReview(self.commit_row.commit_key, approval,
                                    message, upload, False)
        self.change_view.app.backScreen()
        if merge:
            self.change_view.mergeChange()

class CommitRow(urwid.WidgetWrap):
    commit_focus_map = {
                          'commit-name': 'focused-commit-name',
                          'commit-sha': 'focused-commit-sha',
                          'commit-comments': 'focused-commit-comments',
                          'commit-drafts': 'focused-commit-drafts',
                          }

    def __init__(self, app, change_view, repo, commit, expanded=False):
        super(CommitRow, self).__init__(urwid.Pile([]))
        self.app = app
        self.change_view = change_view
        self.commit_key = commit.key
        self.project_name = commit.change.project.name
        self.commit_sha = commit.sha
        self.can_merge = commit.change.canMerge()
        self.title = mywid.TextButton(u'', on_press = self.expandContract)
        table = mywid.Table(columns=3)
        total_added = 0
        total_removed = 0
        for rfile in commit.files:
            if rfile.status is None:
                continue
            added = rfile.inserted or 0
            removed = rfile.deleted or 0
            total_added += added
            total_removed += removed
            table.addRow([urwid.Text(('filename', rfile.display_path), wrap='clip'),
                          urwid.Text([('lines-added', '+%i' % (added,)), ', '],
                                     align=urwid.RIGHT),
                          urwid.Text(('lines-removed', '-%i' % (removed,)))])
        table.addRow([urwid.Text(''),
                      urwid.Text([('lines-added', '+%i' % (total_added,)), ', '],
                                 align=urwid.RIGHT),
                      urwid.Text(('lines-removed', '-%i' % (total_removed,)))])
        table = urwid.Padding(table, width='pack')

        focus_map={'commit-button': 'focused-commit-button'}
        self.review_button = ReviewButton(self)
        buttons = [mywid.FixedButton(('commit-button', "Diff"),
                                     on_press=self.diff),
                   mywid.FixedButton(('commit-button', "Local Checkout"),
                                     on_press=self.checkout),
                   mywid.FixedButton(('commit-button', "Local Cherry-Pick"),
                                     on_press=self.cherryPick)]

        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns(buttons + [urwid.Text('')], dividechars=2)
        buttons = urwid.AttrMap(buttons, 'commit-button')
        self.more = urwid.Pile([table, buttons])
        padded_title = urwid.Padding(self.title, width='pack')
        self.pile = urwid.Pile([padded_title])
        self._w = urwid.AttrMap(self.pile, None, focus_map=self.commit_focus_map)
        self.expanded = False
        self.update(commit)
        if expanded:
            self.expandContract(None)

    def update(self, commit):
        line = [('commit-sha', commit.sha[0:7]),
                ('commit-name', ' %s' % commit.message.split('\n')[0])]
        num_drafts = sum([len(f.draft_comments) for f in commit.files])
        if num_drafts:
            pending_message = commit.getPendingMessage()
            if not pending_message:
                line.append(('commit-drafts', ' (%s draft%s)' % (
                            num_drafts, num_drafts>1 and 's' or '')))
        num_comments = sum([len(f.current_comments) for f in commit.files]) - num_drafts
        if num_comments:
            line.append(('commit-comments', ' (%s inline comment%s)' % (
                        num_comments, num_comments>1 and 's' or '')))
        self.title.text.set_text(line)

    def expandContract(self, button):
        if self.expanded:
            self.pile.contents.pop()
            self.expanded = False
        else:
            self.pile.contents.append((self.more, ('pack', None)))
            self.expanded = True

    def diff(self, button):
        self.change_view.diff(self.commit_key)

    def checkout(self, button):
        self.app.localCheckoutCommit(self.project_name, self.commit_sha)

    def cherryPick(self, button):
        self.app.localCherryPickCommit(self.project_name, self.commit_sha)

class ChangeButton(urwid.Button):
    button_left = urwid.Text(u' ')
    button_right = urwid.Text(u' ')

    def __init__(self, change_view, change_key, text):
        super(ChangeButton, self).__init__('')
        self.set_label(text)
        self.change_view = change_view
        self.change_key = change_key
        urwid.connect_signal(self, 'click',
            lambda button: self.openChange())

    def set_label(self, text):
        super(ChangeButton, self).set_label(text)

    def openChange(self):
        try:
            self.change_view.app.changeScreen(ChangeView(self.change_view.app, self.change_key))
        except hubtty.view.DisplayError as e:
            self.change_view.app.error(e.message)

class ChangeMessageBox(mywid.HyperText):
    def __init__(self, change_view, change, message):
        super(ChangeMessageBox, self).__init__(u'')
        self.change_view = change_view
        self.app = change_view.app
        self.refresh(change, message)

    def formatReply(self):
        text = self.message_text
        pgraphs = []
        pgraph_accumulator = []
        wrap = True
        for line in text.split('\n'):
            if line.startswith('> '):
                wrap = False
                line = '> ' + line
            if not line:
                if pgraph_accumulator:
                    pgraphs.append((wrap, '\n'.join(pgraph_accumulator)))
                    pgraph_accumulator = []
                    wrap = True
                continue
            pgraph_accumulator.append(line)
        if pgraph_accumulator:
            pgraphs.append((wrap, '\n'.join(pgraph_accumulator)))
            pgraph_accumulator = []
            wrap = True
        wrapper = textwrap.TextWrapper(initial_indent='> ',
                                       subsequent_indent='> ')
        wrapped_pgraphs = []
        for wrap, pgraph in pgraphs:
            if wrap:
                wrapped_pgraphs.append('\n'.join(wrapper.wrap(pgraph)))
            else:
                wrapped_pgraphs.append(pgraph)
        return '\n>\n'.join(wrapped_pgraphs)

    def reply(self):
        reply_text = self.formatReply()
        if reply_text:
            reply_text = self.message_author + ' wrote:\n\n' + reply_text + '\n'
        row = self.change_view.commit_rows[self.commit_key]
        row.review_button.openReview(reply_text)

    def refresh(self, change, message):
        self.commit_key = self.change_view.last_commit_key
        self.message_created = message.created
        self.message_author = message.author_name
        self.message_text = message.message
        created = self.app.time(message.created)
        lines = message.message.split('\n')
        if self.app.isOwnAccount(message.author):
            name_style = 'change-message-own-name'
            header_style = 'change-message-own-header'
            reviewer_string = message.author_name
        else:
            name_style = 'change-message-name'
            header_style = 'change-message-header'
            if message.author.email:
                reviewer_string = "%s <%s>" % (
                    message.author_name,
                    message.author.email)
            else:
                reviewer_string = message.author_name

        text = [(name_style, reviewer_string),
                (header_style,
                 created.strftime(' (%Y-%m-%d %H:%M:%S%z)'))]
        if message.draft and not message.pending:
            text.append(('change-message-draft', ' (draft)'))
        else:
            link = mywid.Link('< Reply >',
                              'commit-button',
                              'focused-commit-button')
            urwid.connect_signal(link, 'selected',
                                 lambda link:self.reply())
            text.append(' ')
            text.append(link)

        if lines and lines[-1]:
            lines.insert(0, '')
            lines.append('')
        comment_text = ['\n'.join(lines)]
        for commentlink in self.app.config.commentlinks:
            comment_text = commentlink.run(self.app, comment_text)

        inline_comments = {}
        for comment in message.comments:
            path = comment.file.path
            inline_comments.setdefault(path, [])
            inline_comments[path].append((comment.original_commit_id[0:7], comment.original_line or 0, comment.message))
        for v in inline_comments.values():
            v.sort()

        if inline_comments:
            comment_text.append(u'\n')
        for key, value in inline_comments.items():
            comment_text.append(('filename-inline-comment', u'%s' % key))
            for sha, line, comment in value:
                location_str = ''
                if sha:
                    location_str += sha
                    if line: location_str += ", "
                if line:
                    location_str += str(line)
                if location_str:
                    location_str += ": "
                comment_text.append(u'\n  %s%s\n' % (location_str, comment))

        self.set_text(text+comment_text)

class PrDescriptionBox(mywid.HyperText):
    def __init__(self, app, message):
        self.app = app
        super(PrDescriptionBox, self).__init__(message)

    def set_text(self, text):
        text = [text]
        for commentlink in self.app.config.commentlinks:
            text = commentlink.run(self.app, text)
        super(PrDescriptionBox, self).set_text(text)

@mouse_scroll_decorator.ScrollByWheel
class ChangeView(urwid.WidgetWrap):
    def getCommands(self):
        return [
            (keymap.LOCAL_CHECKOUT,
             "Checkout the change into the local repo"),
            (keymap.DIFF,
             "Show the diff of the first commit"),
            (keymap.TOGGLE_HIDDEN,
             "Toggle the hidden flag for the current change"),
            (keymap.NEXT_CHANGE,
             "Go to the next change in the list"),
            (keymap.PREV_CHANGE,
             "Go to the previous change in the list"),
            (keymap.REVIEW,
             "Leave a review for the change"),
            (keymap.TOGGLE_HELD,
             "Toggle the held flag for the current change"),
            (keymap.TOGGLE_HIDDEN_COMMENTS,
             "Toggle display of hidden comments"),
            (keymap.SEARCH_RESULTS,
             "Back to the list of changes"),
            (keymap.TOGGLE_REVIEWED,
             "Toggle the reviewed flag for the current change"),
            (keymap.TOGGLE_STARRED,
             "Toggle the starred flag for the current change"),
            (keymap.LOCAL_CHERRY_PICK,
             "Cherry-pick the most recent commit onto the local repo"),
            (keymap.CLOSE_CHANGE,
             "Close this change"),
            (keymap.EDIT_PULL_REQUEST,
             "Edit the commit message of this change"),
            (keymap.REBASE_CHANGE,
             "Rebase this change (remotely)"),
            (keymap.REOPEN_CHANGE,
             "Reopen pull request"),
            (keymap.REFRESH,
             "Refresh this change"),
            (keymap.EDIT_LABELS,
             "Edit the labels of this change"),
            (keymap.MERGE_CHANGE,
             "Merge this change"),
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

    def __init__(self, app, change_key):
        super(ChangeView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('hubtty.view.change')
        self.app = app
        self.change_key = change_key
        self.commit_rows = {}
        self.message_rows = {}
        self.first_commit_key = None
        self.last_commit_key = None
        self.hide_comments = True
        self.marked_seen = False
        self.author_label = mywid.TextButton(u'', on_press=self.searchAuthor)
        self.project_label = mywid.TextButton(u'', on_press=self.searchProject)
        self.branch_label = urwid.Text(u'', wrap='clip')
        self.labels_label = mywid.HyperText(u'')
        self.created_label = urwid.Text(u'', wrap='clip')
        self.updated_label = urwid.Text(u'', wrap='clip')
        self.status_label = urwid.Text(u'', wrap='clip')
        self.permalink_label = mywid.TextButton(u'', on_press=self.openPermalink)
        change_info = []
        change_info_map={'change-data': 'focused-change-data'}
        for l, v in [("Author", urwid.Padding(urwid.AttrMap(self.author_label, None,
                                                           focus_map=change_info_map),
                                             width='pack')),
                     ("Project", urwid.Padding(urwid.AttrMap(self.project_label, None,
                                                           focus_map=change_info_map),
                                             width='pack')),
                     ("Branch", self.branch_label),
                     ("Labels", self.labels_label),
                     ("Created", self.created_label),
                     ("Updated", self.updated_label),
                     ("Status", self.status_label),
                     ("Permalink", urwid.Padding(urwid.AttrMap(self.permalink_label, None,
                                                               focus_map=change_info_map),
                                                 width='pack')),
                     ]:
            row = urwid.Columns([(12, urwid.Text(('change-header', l), wrap='clip')), v])
            change_info.append(row)
        change_info = urwid.Pile(change_info)
        self.pr_description = PrDescriptionBox(app, u'')
        votes = mywid.Table([])
        self.depends_on = urwid.Pile([])
        self.depends_on_rows = {}
        self.needed_by = urwid.Pile([])
        self.needed_by_rows = {}
        self.related_changes = urwid.Pile([self.depends_on, self.needed_by])
        self.results = mywid.HyperText(u'') # because it scrolls better than a table
        self.grid = mywid.MyGridFlow([change_info, self.pr_description, votes, self.results],
                                     cell_width=80, h_sep=2, v_sep=1, align='left')
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

        self.listbox.body.append(self.grid)
        self.listbox.body.append(urwid.Divider())
        self.listbox.body.append(self.related_changes)
        self.listbox.body.append(urwid.Divider())
        self.listbox_patchset_start = len(self.listbox.body)

        self.checkGitRepo()
        self.refresh()
        self.listbox.set_focus(0)
        self.grid.set_focus(1)

    def checkGitRepo(self):
        missing_commits = set()
        change_number = None
        change_id = None
        shas = set()
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change_project_name = change.project.name
            change_number = change.number
            change_id = change.change_id
            for commit in change.commits:
                shas.add(commit.parent)
                shas.add(commit.sha)
        repo = gitrepo.get_repo(change_project_name, self.app.config)
        missing_commits = repo.checkCommits(shas)
        if missing_commits:
            if self.app.sync.offline:
                raise hubtty.view.DisplayError("Git commits not present in local repository")
            self.app.log.warning("Missing some commits for change %s %s",
                change_number, missing_commits)
            task = sync.SyncChangeTask(change_id, force_fetch=True,
                                       priority=sync.HIGH_PRIORITY)
            self.app.sync.submitTask(task)
            succeeded = task.wait(300)
            if not succeeded:
                raise hubtty.view.DisplayError("Git commits not present in local repository")

    def interested(self, event):
        if not ((isinstance(event, sync.ChangeAddedEvent) and
                 self.change_key in event.related_change_keys)
                or
                (isinstance(event, sync.ChangeUpdatedEvent) and
                 self.change_key in event.related_change_keys)):
            self.log.debug("Ignoring refresh change due to event %s" % (event,))
            return False
        self.log.debug("Refreshing change due to event %s" % (event,))
        return True

    def refresh(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key, lazy=False)
            # When we first open the change, update its last_seen
            # time.
            if not self.marked_seen:
                change.last_seen = datetime.datetime.utcnow()
                self.marked_seen = True
            self.pending_edit_message = change.pending_edit_message or ''
            reviewed = hidden = starred = held = ''
            if change.reviewed:
                reviewed = ' (reviewed)'
            if change.hidden:
                hidden = ' (hidden)'
            if change.starred:
                starred = '* '
            if change.held:
                held = ' (held)'
            self.title = '%sChange %s%s%s%s' % (starred, change.number, reviewed,
                                                hidden, held)
            self.app.status.update(title=self.title)
            self.project_key = change.project.key
            self.project_name = change.project.name
            self.change_rest_id = change.change_id
            if change.author:
                self.author_login = change.author.username
            else:
                self.author_login = None

            if change.author.email:
                author_string = '%s <%s>' % (change.author_name,
                                            change.author.email)
            else:
                author_string = change.author_name
            self.author_label.text.set_text(('change-data', author_string))
            self.project_label.text.set_text(('change-data', change.project.name))
            self.branch_label.set_text(('change-data', change.branch))
            label_buttons = []
            for x in change.labels:
                if label_buttons:
                    label_buttons.append(', ')
                link = mywid.Link(x.name, 'change-data', 'focused-change-data')
                urwid.connect_signal(
                    link, 'selected',
                    lambda link, x=x: self.searchLabel(x.name))
                label_buttons.append(link)
            self.labels_label.set_text(('change-data', label_buttons or u''))
            self.created_label.set_text(('change-data', str(self.app.time(change.created))))
            self.updated_label.set_text(('change-data', str(self.app.time(change.updated))))
            self.status_label.set_text(('change-data', change.state))
            self.permalink_url = str(change.html_url)
            self.permalink_label.text.set_text(('change-data', self.permalink_url))
            self.pr_description.set_text('\n'.join([change.title, '', change.body]))

            review_states = ['Changes Requested', 'Comment', 'Approved']
            approval_headers = [urwid.Text(('table-header', 'Name'))]
            for state in review_states:
                approval_headers.append(urwid.Text(('table-header', state)))
            votes = mywid.Table(approval_headers)
            approvals_for_account = {}
            pending_message = change.commits[-1].getPendingMessage()
            for approval in change.approvals:
                # Don't display draft approvals unless they are pending-upload
                if approval.draft and not pending_message:
                    continue
                approvals = approvals_for_account.get(approval.reviewer.id)
                if not approvals:
                    approvals = {}
                    row = []
                    if self.app.isOwnAccount(approval.reviewer):
                        style = 'reviewer-own-name'
                    else:
                        style = 'reviewer-name'
                    row.append(urwid.Text((style, approval.reviewer_name)))
                    for i, state in enumerate(review_states):
                        w = urwid.Text(u'', align=urwid.CENTER)
                        approvals[state] = w
                        row.append(w)
                    approvals_for_account[approval.reviewer.id] = approvals
                    votes.addRow(row)
                # Only set approval status if the review is for the current commit
                if approval.sha == change.commits[-1].sha:
                    if approval.state in ['APPROVED', 'APPROVE']:
                        approvals['Approved'].set_text(('positive-label', '✓'))
                    elif approval.state in ['CHANGES_REQUESTED', 'REQUEST_CHANGES']:
                        approvals['Changes Requested'].set_text(('negative-label', '✗'))
                    else:
                        approvals['Comment'].set_text('•')
            votes = urwid.Padding(votes, width='pack')

            # TODO: update the existing table rather than replacing it
            # wholesale.  It will become more important if the table
            # gets selectable items (like clickable names).
            self.grid.contents[2] = (votes, ('given', 80))

            # self.refreshDependencies(session, change)

            repo = gitrepo.get_repo(change.project.name, self.app.config)
            # The listbox has both commits and messages in it (and
            # may later contain the vote table and change header), so
            # keep track of the index separate from the loop.
            listbox_index = self.listbox_patchset_start
            self.first_commit_key = change.commits[0].key
            for commit in change.commits:
                self.last_commit_key = commit.key
                row = self.commit_rows.get(commit.key)
                if not row:
                    row = CommitRow(self.app, self, repo, commit)
                    self.listbox.body.insert(listbox_index, row)
                    self.commit_rows[commit.key] = row
                row.update(commit)
                # Revisions are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1
            if len(self.listbox.body) == listbox_index:
                self.listbox.body.insert(listbox_index, urwid.Divider())
            listbox_index += 1
            # Get the set of messages that should be displayed
            display_messages = []
            result_systems = {}
            for message in change.messages:
                if (message.commit == change.commits[-1] and
                    message.author and message.author.name):
                    for commentlink in self.app.config.commentlinks:
                        results = commentlink.getTestResults(self.app, message.message)
                        if results:
                            result_system = result_systems.get(message.author.name,
                                                               OrderedDict())
                            result_systems[message.author.name] = result_system
                            result_system.update(results)
                skip = False
                if self.hide_comments and message.author and message.author.username:
                    for regex in self.app.config.hide_comments:
                        if regex.match(message.author.username):
                            skip = True
                            break
                if not skip:
                    display_messages.append(message)
            # The set of message keys currently displayed
            unseen_keys = set(self.message_rows.keys())
            # Make sure all of the messages that should be displayed are
            for message in display_messages:
                row = self.message_rows.get(message.key)
                if not row:
                    box = ChangeMessageBox(self, change, message)
                    row = urwid.Padding(box, width=80)
                    self.listbox.body.insert(listbox_index, row)
                    self.message_rows[message.key] = row
                else:
                    unseen_keys.remove(message.key)
                    if message.created != row.original_widget.message_created:
                        row.original_widget.refresh(change, message)
                listbox_index += 1
            # Remove any messages that should not be displayed
            for key in unseen_keys:
                row = self.message_rows.get(key)
                self.listbox.body.remove(row)
                del self.message_rows[key]
                listbox_index -= 1
            self._updateTestResults(change, result_systems)

    def _add_link(self, name, url):
        link = mywid.Link('{:<42}'.format(name), 'link', 'focused-link')
        if url:
            urwid.connect_signal(link, 'selected', lambda link:self.app.openURL(url))
        return link

    def _updateTestResults(self, change, result_systems):
        text = []
        for system, results in result_systems.items():
            for job, result in results.items():
                text.append(result)

        # Add check results
        commit = change.commits[-1]
        for check in commit.checks:
            if not (check.url or check.message):
                continue
            # link check name/url, color result, in time
            color = 'check-%s' % check.state
            result = (color, check.message)
            line = [self._add_link(check.name, check.url), result]
            if check.finished and check.started:
                line.append(' in %s' % (check.finished-check.started))
            line.append('\n')
            text.append(line)

        if text:
            self.results.set_text(text)
        else:
            self.results.set_text('')

    def _updateDependenciesWidget(self, changes, widget, widget_rows, header):
        if not changes:
            if len(widget.contents) > 0:
                widget.contents[:] = []
            return

        if len(widget.contents) == 0:
            widget.contents.append((urwid.Text(('table-header', header)),
                                    widget.options()))

        unseen_keys = set(widget_rows.keys())
        i = 1
        for key, title in changes.items():
            row = widget_rows.get(key)
            if not row:
                row = urwid.AttrMap(urwid.Padding(ChangeButton(self, key, title), width='pack'),
                                    'link', focus_map={None: 'focused-link'})
                row = (row, widget.options('pack'))
                widget.contents.insert(i, row)
                if not widget.selectable():
                    widget.set_focus(i)
                if not self.related_changes.selectable():
                    self.related_changes.set_focus(widget)
                widget_rows[key] = row
            else:
                row[0].original_widget.original_widget.set_label(title)
                unseen_keys.remove(key)
            i += 1
        for key in unseen_keys:
            row = widget_rows[key]
            widget.contents.remove(row)
            del widget_rows[key]

    def refreshDependencies(self, session, change):
        commit = change.commits[-1]

        # Handle depends-on
        parents = {}
        parent = change.getCommitBySha(commit.parent)
        if parent:
            title = parent.change.title
            show_merged = False
            if parent != parent.change.commits[-1]:
                title += ' [OUTDATED]'
                show_merged = True
            if parent.change.state == 'closed' and not parent.change.merged:
                title += ' [CLOSED]'
            if show_merged or parent.change.merged:
                parents[parent.change.key] = title
        self._updateDependenciesWidget(parents,
                                       self.depends_on, self.depends_on_rows,
                                       header='Depends on:')

        # Handle needed-by
        children = {}
        children.update((r.change.key, r.change.title)
                        for r in session.getCommitsByParent([commit.sha for commit in change.commits])
                        if (r.change.state == 'open' and r == r.change.commits[-1]))
        self._updateDependenciesWidget(children,
                                       self.needed_by, self.needed_by_rows,
                                       header='Needed by:')


    def toggleReviewed(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.reviewed = not change.reviewed
            self.app.project_cache.clear(change.project)

    def toggleHidden(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.hidden = not change.hidden
            self.app.project_cache.clear(change.project)

    def toggleStarred(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.starred = not change.starred
            self.app.project_cache.clear(change.project)

    def toggleHeld(self):
        return self.app.toggleHeldChange(self.change_key)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ChangeView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.TOGGLE_REVIEWED in commands:
            self.toggleReviewed()
            self.refresh()
            return None
        if keymap.TOGGLE_HIDDEN in commands:
            self.toggleHidden()
            self.refresh()
            return None
        if keymap.TOGGLE_STARRED in commands:
            self.toggleStarred()
            self.refresh()
            return None
        if keymap.TOGGLE_HELD in commands:
            self.toggleHeld()
            self.refresh()
            return None
        if keymap.REVIEW in commands:
            row = self.commit_rows[self.last_commit_key]
            row.review_button.openReview()
            return None
        if keymap.DIFF in commands:
            row = self.commit_rows[self.first_commit_key]
            row.diff(None)
            return None
        if keymap.LOCAL_CHECKOUT in commands:
            row = self.commit_rows[self.last_commit_key]
            row.checkout(None)
            return None
        if keymap.LOCAL_CHERRY_PICK in commands:
            row = self.commit_rows[self.last_commit_key]
            row.cherryPick(None)
            return None
        if keymap.SEARCH_RESULTS in commands:
            widget = self.app.findChangeList()
            if widget:
                self.app.backScreen(widget)
            return None
        if ((keymap.NEXT_CHANGE in commands) or
            (keymap.PREV_CHANGE in commands)):
            widget = self.app.findChangeList()
            if widget:
                if keymap.NEXT_CHANGE in commands:
                    new_change_key = widget.getNextChangeKey(self.change_key)
                else:
                    new_change_key = widget.getPrevChangeKey(self.change_key)
                if new_change_key:
                    try:
                        view = ChangeView(self.app, new_change_key)
                        self.app.changeScreen(view, push=False)
                    except hubtty.view.DisplayError as e:
                        self.app.error(e.message)
            return None
        if keymap.TOGGLE_HIDDEN_COMMENTS in commands:
            self.hide_comments = not self.hide_comments
            self.refresh()
            return None
        if keymap.CLOSE_CHANGE in commands:
            self.closeChange()
            return None
        if keymap.EDIT_PULL_REQUEST in commands:
            self.editPullRequest()
            return None
        if keymap.REBASE_CHANGE in commands:
            self.rebaseChange()
            return None
        if keymap.REOPEN_CHANGE in commands:
            self.reopenChange()
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncChangeTask(self.change_rest_id, priority=sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        if keymap.MERGE_CHANGE in commands:
            self.mergeChange()
            return None
        if keymap.EDIT_LABELS in commands:
            self.editLabels()
            return None
        if key in self.app.config.reviewkeys:
            self.reviewKey(self.app.config.reviewkeys[key])
            return None
        return key

    def diff(self, commit_key):
        if self.app.config.diff_view == 'unified':
            screen = view_unified_diff.UnifiedDiffView(self.app, commit_key)
        else:
            screen = view_side_diff.SideDiffView(self.app, commit_key)
        self.app.changeScreen(screen)

    def closeChange(self):
        dialog = mywid.TextEditDialog(u'Close pull request', u'Message:',
                                      u'Close pull request',
                                      self.pending_edit_message)
        urwid.connect_signal(dialog, 'cancel', lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCloseReopenChange(dialog, 'closed'))
        self.app.popup(dialog)

    def reopenChange(self):
        dialog = mywid.TextEditDialog(u'Reopen pull request', u'Message:',
                                      u'Reopen pull request',
                                      self.pending_edit_message)
        urwid.connect_signal(dialog, 'cancel', lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCloseReopenChange(dialog, 'open'))
        self.app.popup(dialog)

    def doCloseReopenChange(self, dialog, state):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.state = state
            change.pending_edit = True
            change.pending_edit_message = dialog.entry.edit_text
            change_key = change.key
        self.app.sync.submitTask(
            sync.EditPullRequestTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def editPullRequest(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            dialog = EditPullRequestDialog(self.app, change)
        urwid.connect_signal(dialog, 'cancel',
                    lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doEditPullRequest(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def doEditPullRequest(self, dialog):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.title = dialog.pr_title.edit_text
            change.body = dialog.pr_description.edit_text
            change.pending_edit = True
            change_key = change.key
        self.app.sync.submitTask(
            sync.EditPullRequestTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def rebaseChange(self):
        dialog = mywid.YesNoDialog(u'Rebase Change',
                                   u'Perform a remote rebase of this change?')
        urwid.connect_signal(dialog, 'no', self.app.backScreen)
        urwid.connect_signal(dialog, 'yes', self.doRebaseChange)
        self.app.popup(dialog)

    def doRebaseChange(self, button=None):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.pending_rebase = True
            change_key = change.key
        self.app.sync.submitTask(
            sync.RebaseChangeTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def mergeChange(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            dialog = MergeDialog(self.app, change)
        urwid.connect_signal(dialog, 'cancel',
                    lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'merge', lambda button:
                                 self.doMergeChange(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def doMergeChange(self, dialog):
        pending_merge = None

        strategy, title, message = dialog.getValues()

        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)

            if not change.canMerge():
                error_dialog = mywid.MessageDialog('Error', 'You cannot merge this change.')
                urwid.connect_signal(error_dialog, 'close',
                    lambda button: self.app.backScreen())
                self.app.popup(error_dialog)
                return

            sha = change.commits[-1].sha
            pending_merge = change.createPendingMerge(sha, strategy,
                    commit_title=title, commit_message=message)

        if pending_merge:
            self.app.sync.submitTask(
                    sync.SendMergeTask(pending_merge.key, sync.HIGH_PRIORITY))

        self.app.backScreen()
        self.refresh()

    def editLabels(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            dialog = EditLabelsDialog(self.app, change)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeEditLabels(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeEditLabels(dialog, False))
        self.app.popup(dialog)

    def closeEditLabels(self, dialog, save):
        if save:
            change_key = None
            labels_to_set = [ cb.label for cb in dialog.labels_checkboxes if cb.state ]
            with self.app.db.getSession() as session:
                change = session.getChange(self.change_key)
                for label in change.project.labels:
                    if label.name in labels_to_set and label not in change.labels:
                        change.addLabel(label)
                    if label.name not in labels_to_set and label in change.labels:
                        change.removeLabel(label)
                change.pending_labels = True
                change_key = change.key
            self.app.sync.submitTask(
                sync.SetLabelsTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def openPermalink(self, widget):
        self.app.openURL(self.permalink_url)

    def searchAuthor(self, widget):
        if self.author_login:
            self.app.doSearch("state:open author:%s" % (self.author_login,))

    def searchProject(self, widget):
        self.app.doSearch("state:open repo:%s" % (self.project_name,))

    def searchLabel(self, name):
        self.app.doSearch("state:open repo:%s label:%s" % (self.project_name, name,))

    def reviewKey(self, reviewkey):
        approval = reviewkey.get('approval', 'COMMENT')
        self.app.log.debug("Reviewkey %s with approval %s" %
                           (reviewkey['key'], approval))
        row = self.commit_rows[self.last_commit_key]
        message = reviewkey.get('message', '')
        merge = reviewkey.get('merge', False)
        upload = not reviewkey.get('draft', False)
        self.saveReview(row.commit_key, approval, message, upload, merge)

    def saveReview(self, commit_key, approval, message, upload, merge):
        message_keys = self.app.saveReviews([commit_key], approval,
                                            message, upload, merge)
        if upload:
            for message_key in message_keys:
                self.app.sync.submitTask(
                    sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
        if self.app.config.close_change_on_review:
            self.app.backScreen()
