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

import logging
import urwid

from hubtty import keymap
from hubtty import mywid
from hubtty import sync
from hubtty.view import pull_request_list as view_pr_list
from hubtty.view import mouse_scroll_decorator

class TopicSelectDialog(urwid.WidgetWrap):
    signals = ['ok', 'cancel']

    def __init__(self, title, topics):
        button_widgets = []
        ok_button = mywid.FixedButton('OK')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(ok_button, 'click',
                             lambda button:self._emit('ok'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        button_widgets.append(('pack', ok_button))
        button_widgets.append(('pack', cancel_button))
        button_columns = urwid.Columns(button_widgets, dividechars=2)

        self.topic_buttons = []
        self.topic_keys = {}
        rows = []
        for key, name in topics:
            button = mywid.FixedRadioButton(self.topic_buttons, name)
            self.topic_keys[button] = key
            rows.append(button)

        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(TopicSelectDialog, self).__init__(urwid.LineBox(fill, title))

    def getSelected(self):
        for b in self.topic_buttons:
            if b.state:
                return self.topic_keys[b]
        return None

class RepositoryRow(urwid.Button):
    repository_focus_map = {None: 'focused',
                         'unreviewed-repository': 'focused-unreviewed-repository',
                         'subscribed-repository': 'focused-subscribed-repository',
                         'unsubscribed-repository': 'focused-unsubscribed-repository',
                         'marked-repository': 'focused-marked-repository',
    }

    def selectable(self):
        return True

    def _setName(self, name, indent):
        self.repository_name = name
        name = indent+name
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, app, repository, topic, callback=None):
        super(RepositoryRow, self).__init__('', on_press=callback,
                                         user_data=(repository.key, repository.name))
        self.app = app
        self.mark = False
        self._style = None
        self.repository_key = repository.key
        if topic:
            self.topic_key = topic.key
            self.indent = '  '
        else:
            self.topic_key = None
            self.indent = ''
        self.repository_name = repository.name
        self.name = mywid.SearchableText('')
        self._setName(repository.name, self.indent)
        self.name.set_wrap_mode('clip')
        self.unreviewed_prs = urwid.Text(u'', align=urwid.RIGHT)
        self.open_prs = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                self.name,
                ('fixed', 11, self.unreviewed_prs),
                ('fixed', 5, self.open_prs),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.repository_focus_map)
        self.update(repository)

    def search(self, search, attribute):
        return self.name.search(search, attribute)

    def update(self, repository):
        cache = self.app.repository_cache.get(repository)
        if repository.subscribed:
            if cache['unreviewed_prs'] > 0:
                style = 'unreviewed-repository'
            else:
                style = 'subscribed-repository'
        else:
            style = 'unsubscribed-repository'
        self._style = style
        if self.mark:
            style = 'marked-repository'
        self.row_style.set_attr_map({None: style})
        self.unreviewed_prs.set_text('%i ' % cache['unreviewed_prs'])
        self.open_prs.set_text('%i ' % cache['open_prs'])

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-repository'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.repository_name, self.indent)

class TopicRow(urwid.Button):
    repository_focus_map = {None: 'focused',
                           'subscribed-repository': 'focused-subscribed-repository',
                           'marked-repository': 'focused-marked-repository',
    }

    def selectable(self):
        return True

    def _setName(self, name):
        self.topic_name = name
        name = '[[ '+name+' ]]'
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, topic, callback=None):
        super(TopicRow, self).__init__('', on_press=callback,
                                       user_data=(topic.key, topic.name))
        self.mark = False
        self._style = None
        self.topic_key = topic.key
        self.name = urwid.Text('')
        self._setName(topic.name)
        self.name.set_wrap_mode('clip')
        self.unreviewed_prs = urwid.Text(u'', align=urwid.RIGHT)
        self.open_prs = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                self.name,
                ('fixed', 11, self.unreviewed_prs),
                ('fixed', 5, self.open_prs),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.repository_focus_map)
        self._style = 'subscribed-repository'
        self.row_style.set_attr_map({None: self._style})
        self.update(topic)

    def update(self, topic, unreviewed_prs=None, open_prs=None):
        self._setName(topic.name)
        if unreviewed_prs is None:
            self.unreviewed_prs.set_text('')
        else:
            self.unreviewed_prs.set_text('%i ' % unreviewed_prs)
        if open_prs is None:
            self.open_prs.set_text('')
        else:
            self.open_prs.set_text('%i ' % open_prs)

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-repository'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.topic_name)

class RepositoryListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [urwid.Text(u' Repository'),
                (11, urwid.Text(u'Unreviewed')),
                (5, urwid.Text(u'Open'))]
        super(RepositoryListHeader, self).__init__(urwid.Columns(cols))

@mouse_scroll_decorator.ScrollByWheel
class RepositoryListView(urwid.WidgetWrap, mywid.Searchable):
    def getCommands(self):
        return [
            (keymap.TOGGLE_LIST_SUBSCRIBED,
             "Toggle whether only subscribed repos or all repos are listed"),
            (keymap.TOGGLE_LIST_REVIEWED,
             "Toggle listing of repositories with unreviewed pull requests"),
            (keymap.TOGGLE_SUBSCRIBED,
             "Toggle the subscription flag for the selected repository"),
            (keymap.REFRESH,
             "Sync subscribed repositories"),
            (keymap.TOGGLE_MARK,
             "Toggle the process mark for the selected repository"),
            (keymap.NEW_REPOSITORY_TOPIC,
             "Create repository topic"),
            (keymap.DELETE_REPOSITORY_TOPIC,
             "Delete selected repository topic"),
            (keymap.MOVE_REPOSITORY_TOPIC,
             "Move selected repository to topic"),
            (keymap.COPY_REPOSITORY_TOPIC,
             "Copy selected repository to topic"),
            (keymap.REMOVE_REPOSITORY_TOPIC,
             "Remove selected repository from topic"),
            (keymap.RENAME_REPOSITORY_TOPIC,
             "Rename selected repository topic"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
        ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app):
        super(RepositoryListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('hubtty.view.repository_list')
        self.searchInit()
        self.app = app
        self.unreviewed = True
        self.subscribed = True
        self.repository_rows = {}
        self.topic_rows = {}
        self.open_topics = set()
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.header = RepositoryListHeader()
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def interested(self, event):
        if not (isinstance(event, sync.RepositoryAddedEvent)
                or
                isinstance(event, sync.PullRequestAddedEvent)
                or
                (isinstance(event, sync.PullRequestUpdatedEvent) and
                 (event.state_changed or event.review_flag_changed))):
            self.log.debug("Ignoring refresh repository list due to event %s" % (event,))
            return False
        self.log.debug("Refreshing repository list due to event %s" % (event,))
        return True

    def advance(self):
        pos = self.listbox.focus_position
        if pos < len(self.listbox.body)-1:
            pos += 1
            self.listbox.focus_position = pos

    def _deleteRow(self, row):
        if row in self.listbox.body:
            self.listbox.body.remove(row)
        if isinstance(row, RepositoryRow):
            del self.repository_rows[(row.topic_key, row.repository_key)]
        else:
            del self.topic_rows[row.topic_key]

    def _repositoryRow(self, i, repository, topic):
        # Ensure that the row at i is the given repository.  If the row
        # already exists somewhere in the list, delete all rows
        # between i and the row and then update the row.  If the row
        # does not exist, insert the row at position i.
        topic_key = topic and topic.key or None
        key = (topic_key, repository.key)
        row = self.repository_rows.get(key)
        while row:  # This is "if row: while True:".
            if i >= len(self.listbox.body):
                break
            current_row = self.listbox.body[i]
            if (isinstance(current_row, RepositoryRow) and
                current_row.repository_key == repository.key):
                break
            self._deleteRow(current_row)
        if not row:
            row = RepositoryRow(self.app, repository, topic, self.onSelect)
            self.listbox.body.insert(i, row)
            self.repository_rows[key] = row
        else:
            row.update(repository)
        return i+1

    def _topicRow(self, i, topic):
        row = self.topic_rows.get(topic.key)
        while row:  # This is "if row: while True:".
            if i >= len(self.listbox.body):
                break
            current_row = self.listbox.body[i]
            if (isinstance(current_row, TopicRow) and
                current_row.topic_key == topic.key):
                break
            self._deleteRow(current_row)
        if not row:
            row = TopicRow(topic, self.onSelectTopic)
            self.listbox.body.insert(i, row)
            self.topic_rows[topic.key] = row
        else:
            row.update(topic)
        return i + 1

    def refresh(self):
        if self.subscribed:
            self.title = u'Subscribed repositories'
            self.short_title = self.title[:]
            if self.unreviewed:
                self.title += u' with unreviewed pull requests'
        else:
            self.title = u'All repositories'
            self.short_title = self.title[:]
        self.app.status.update(title=self.title)
        with self.app.db.getSession() as session:
            i = 0
            for repository in session.getRepositories(topicless=True,
                    subscribed=self.subscribed, unreviewed=self.unreviewed):
                i = self._repositoryRow(i, repository, None)
            for topic in session.getTopics():
                i = self._topicRow(i, topic)
                topic_unreviewed = 0
                topic_open = 0
                for repository in topic.repositories:
                    cache = self.app.repository_cache.get(repository)
                    topic_unreviewed += cache['unreviewed_prs']
                    topic_open += cache['open_prs']
                    if self.subscribed:
                        if not repository.subscribed:
                            continue
                        if self.unreviewed and not cache['unreviewed_prs']:
                            continue
                    if topic.key in self.open_topics:
                        i = self._repositoryRow(i, repository, topic)
                topic_row = self.topic_rows.get(topic.key)
                topic_row.update(topic, topic_unreviewed, topic_open)
        while i < len(self.listbox.body):
            current_row = self.listbox.body[i]
            self._deleteRow(current_row)

    def onSelect(self, button, data):
        repository_key, repository_name = data
        self.app.changeScreen(view_pr_list.PullRequestListView(
                self.app,
                "_repository_key:%s %s" % (repository_key, self.app.config.repository_pr_list_query),
                repository_name, repository_key=repository_key, unreviewed=True))

    def onSelectTopic(self, button, data):
        topic_key = data[0]
        self.open_topics ^= set([topic_key])
        self.refresh()

    def toggleMark(self):
        if not len(self.listbox.body):
            return
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        row.toggleMark()
        self.advance()

    def createTopic(self):
        dialog = mywid.LineEditDialog(self.app, 'Topic', 'Create a new topic.',
                                      'Topic: ', '', self.app.ring)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeCreateTopic(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeCreateTopic(dialog, False))
        self.app.popup(dialog)

    def closeCreateTopic(self, dialog, save):
        if save:
            last_topic_key = None
            for row in self.listbox.body:
                if isinstance(row, TopicRow):
                    last_topic_key = row.topic_key
            with self.app.db.getSession() as session:
                if last_topic_key:
                    last_topic = session.getTopic(last_topic_key)
                    seq = last_topic.sequence + 1
                else:
                    seq = 0
                session.createTopic(dialog.entry.edit_text, seq)
        self.app.backScreen()

    def deleteTopic(self):
        rows = self.getSelectedRows(TopicRow)
        if not rows:
            return
        with self.app.db.getSession() as session:
            for row in rows:
                topic = session.getTopic(row.topic_key)
                session.delete(topic)
        self.refresh()

    def renameTopic(self):
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        if not isinstance(row, TopicRow):
            return
        with self.app.db.getSession() as session:
            topic = session.getTopic(row.topic_key)
            name = topic.name
            key = topic.key
        dialog = mywid.LineEditDialog(self.app, 'Topic', 'Rename a new topic.',
                                      'Topic: ', name, self.app.ring)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeRenameTopic(dialog, True, key))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeRenameTopic(dialog, False, key))
        self.app.popup(dialog)

    def closeRenameTopic(self, dialog, save, key):
        if save:
            with self.app.db.getSession() as session:
                topic = session.getTopic(key)
                topic.name = dialog.entry.edit_text
        self.app.backScreen()

    def getSelectedRows(self, cls):
        ret = []
        if not self.listbox.body:
            return []
        for row in self.listbox.body:
            if isinstance(row, cls) and row.mark:
                ret.append(row)
        if ret:
            return ret
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        if isinstance(row, cls):
            return [row]
        return []

    def copyMoveToTopic(self, move):
        if move:
            verb = 'Move'
        else:
            verb = 'Copy'
        rows = self.getSelectedRows(RepositoryRow)
        if not rows:
            return

        with self.app.db.getSession() as session:
            topics = [(t.key, t.name) for t in session.getTopics()]

        dialog = TopicSelectDialog('%s to Topic' % verb, topics)
        urwid.connect_signal(dialog, 'ok',
            lambda button: self.closeCopyMoveToTopic(dialog, True, rows, move))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeCopyMoveToTopic(dialog, False, rows, move))
        self.app.popup(dialog)

    def closeCopyMoveToTopic(self, dialog, save, rows, move):
        error = None
        if save:
            with self.app.db.getSession() as session:
                key = dialog.getSelected()
                new_topic = session.getTopic(key)
                if not new_topic:
                    error = "Unable to find topic %s" % key
                else:
                    for row in rows:
                        repository = session.getRepository(row.repository_key)
                        if move and row.topic_key:
                            old_topic = session.getTopic(row.topic_key)
                            self.log.debug("Remove %s from %s" % (repository, old_topic))
                            old_topic.removeRepository(repository)
                        self.log.debug("Add %s to %s" % (repository, new_topic))
                        new_topic.addRepository(repository)
        self.app.backScreen()
        if error:
            self.app.error(error)

    def moveToTopic(self):
        self.copyMoveToTopic(True)

    def copyToTopic(self):
        self.copyMoveToTopic(False)

    def removeFromTopic(self):
        rows = self.getSelectedRows(RepositoryRow)
        rows = [r for r in rows if r.topic_key]
        if not rows:
            return
        with self.app.db.getSession() as session:
            for row in rows:
                repository = session.getRepository(row.repository_key)
                topic = session.getTopic(row.topic_key)
                self.log.debug("Remove %s from %s" % (repository, topic))
                topic.removeRepository(repository)
        self.refresh()

    def toggleSubscribed(self):
        rows = self.getSelectedRows(RepositoryRow)
        if not rows:
            return
        keys = [row.repository_key for row in rows]
        subscribed_keys = []
        with self.app.db.getSession() as session:
            for key in keys:
                repository = session.getRepository(key)
                repository.subscribed = not repository.subscribed
                if repository.subscribed:
                    subscribed_keys.append(key)
        for row in rows:
            if row.mark:
                row.toggleMark()
        for key in subscribed_keys:
            self.app.sync.submitTask(sync.SyncRepositoryTask(key))
        self.refresh()

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(RepositoryListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        ret = self.handleCommands(commands)
        if ret is True:
            if keymap.FURTHER_INPUT not in commands:
                self.app.clearInputBuffer()
            return None
        return key

    def handleCommands(self, commands):
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return True
        if keymap.TOGGLE_LIST_SUBSCRIBED in commands:
            self.subscribed = not self.subscribed
            self.refresh()
            return True
        if keymap.TOGGLE_SUBSCRIBED in commands:
            self.toggleSubscribed()
            return True
        if keymap.TOGGLE_MARK in commands:
            self.toggleMark()
            return True
        if keymap.NEW_REPOSITORY_TOPIC in commands:
            self.createTopic()
            return True
        if keymap.DELETE_REPOSITORY_TOPIC in commands:
            self.deleteTopic()
            return True
        if keymap.COPY_REPOSITORY_TOPIC in commands:
            self.copyToTopic()
            return True
        if keymap.MOVE_REPOSITORY_TOPIC in commands:
            self.moveToTopic()
            return True
        if keymap.REMOVE_REPOSITORY_TOPIC in commands:
            self.removeFromTopic()
            return True
        if keymap.RENAME_REPOSITORY_TOPIC in commands:
            self.renameTopic()
            return True
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncSubscribedRepositoriesTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            self.refresh()
            return True
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return True
        return False
