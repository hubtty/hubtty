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

DEFAULT_PALETTE={
    'focused': ['default,standout', ''],
    'header': ['white,bold', 'dark blue'],
    'error': ['light red', 'dark blue'],
    'table-header': ['white,bold', ''],
    'filename': ['light cyan', ''],
    'filename-inline-comment': ['dark cyan', ''],
    'focused-filename': ['light cyan,standout', ''],
    'positive-label': ['dark green', ''],
    'negative-label': ['dark red', ''],
    'max-label': ['light green', ''],
    'min-label': ['light red', ''],
    'focused-positive-label': ['dark green,standout', ''],
    'focused-negative-label': ['dark red,standout', ''],
    'focused-max-label': ['light green,standout', ''],
    'focused-min-label': ['light red,standout', ''],
    'link': ['dark blue', ''],
    'focused-link': ['light blue', ''],
    'footer': ['light gray', 'dark gray'],
    # Diff
    'context-button': ['dark magenta', ''],
    'focused-context-button': ['light magenta', ''],
    'removed-line': ['dark red', ''],
    'removed-word': ['light red', ''],
    'added-line': ['dark green', ''],
    'added-word': ['light green', ''],
    'nonexistent': ['default', ''],
    'focused-removed-line': ['dark red,standout', ''],
    'focused-removed-word': ['light red,standout', ''],
    'focused-added-line': ['dark green,standout', ''],
    'focused-added-word': ['light green,standout', ''],
    'focused-nonexistent': ['default,standout', ''],
    'draft-comment': ['default', 'dark gray'],
    'comment': ['light gray', 'dark gray'],
    'comment-name': ['white', 'dark gray'],
    'line-number': ['dark gray', ''],
    'focused-line-number': ['dark gray,standout', ''],
    'search-result': ['default,standout', ''],
    'trailing-ws': ['light red,standout', ''],
    # Pull request view
    'pr-data': ['dark cyan', ''],
    'focused-pr-data': ['light cyan', ''],
    'pr-header': ['light blue', ''],
    'commit-name': ['light blue', ''],
    'commit-sha': ['dark blue', ''],
    'commit-comments': ['default', ''],
    'commit-drafts': ['dark red', ''],
    'focused-commit-name': ['light blue,standout', ''],
    'focused-commit-sha': ['dark blue,standout', ''],
    'focused-commit-comments': ['default,standout', ''],
    'focused-commit-drafts': ['dark red,standout', ''],
    'commit-button': ['dark magenta', ''],
    'focused-commit-button': ['light magenta', ''],
    'pr-message-name': ['yellow', ''],
    'pr-message-own-name': ['light cyan', ''],
    'pr-message-header': ['brown', ''],
    'pr-message-own-header': ['dark cyan', ''],
    'pr-message-draft': ['dark red', ''],
    'lines-added': ['light green', ''],
    'lines-removed': ['light red', ''],
    'reviewer-name': ['yellow', ''],
    'reviewer-own-name': ['light cyan', ''],
    'check-success': ['light green', ''],
    'check-failure': ['light red', ''],
    'check-pending': ['dark magenta', ''],
    # repository list
    'unreviewed-repository': ['white', ''],
    'subscribed-repository': ['default', ''],
    'unsubscribed-repository': ['dark gray', ''],
    'marked-repository': ['light cyan', ''],
    'focused-unreviewed-repository': ['white,standout', ''],
    'focused-subscribed-repository': ['default,standout', ''],
    'focused-unsubscribed-repository': ['dark gray,standout', ''],
    'focused-marked-repository': ['light cyan,standout', ''],
    # Pull request list
    'unreviewed-pr': ['default', ''],
    'reviewed-pr': ['dark gray', ''],
    'focused-unreviewed-pr': ['default,standout', ''],
    'focused-reviewed-pr': ['dark gray,standout', ''],
    'starred-pr': ['light cyan', ''],
    'focused-starred-pr': ['light cyan,standout', ''],
    'held-pr': ['light red', ''],
    'focused-held-pr': ['light red,standout', ''],
    'marked-pr': ['dark cyan', ''],
    'focused-marked-pr': ['dark cyan,standout', ''],
    'added-graph': ['dark green', ''],
    'removed-graph': ['dark red', ''],
    'added-removed-graph': ['dark green', 'dark red'],
    'focused-added-graph': ['default,standout', 'dark green'],
    'focused-removed-graph': ['default,standout', 'dark red'],
    'line-count-threshold-1': ['light green', ''],
    'focused-line-count-threshold-1': ['light green,standout', ''],
    'line-count-threshold-2': ['light cyan', ''],
    'focused-line-count-threshold-2': ['light cyan,standout', ''],
    'line-count-threshold-3': ['light blue', ''],
    'focused-line-count-threshold-3': ['light blue,standout', ''],
    'line-count-threshold-4': ['yellow', ''],
    'focused-line-count-threshold-4': ['yellow,standout', ''],
    'line-count-threshold-5': ['dark magenta', ''],
    'focused-line-count-threshold-5': ['dark magenta,standout', ''],
    'line-count-threshold-6': ['light magenta', ''],
    'focused-line-count-threshold-6': ['light magenta,standout', ''],
    'line-count-threshold-7': ['dark red', ''],
    'focused-line-count-threshold-7': ['dark red,standout', ''],
    'line-count-threshold-8': ['light red', ''],
    'focused-line-count-threshold-8': ['light red,standout', ''],
    }

# A delta from the default palette
LIGHT_PALETTE = {
    'table-header': ['black,bold', ''],
    'unreviewed-repository': ['black', ''],
    'subscribed-repository': ['dark gray', ''],
    'unsubscribed-repository': ['dark gray', ''],
    'focused-unreviewed-repository': ['black,standout', ''],
    'focused-subscribed-repository': ['dark gray,standout', ''],
    'focused-unsubscribed-repository': ['dark gray,standout', ''],
    'pr-data': ['dark blue,bold', ''],
    'focused-pr-data': ['dark blue,standout', ''],
    'reviewer-name': ['brown', ''],
    'reviewer-own-name': ['dark blue,bold', ''],
    'pr-message-name': ['brown', ''],
    'pr-message-own-name': ['dark blue,bold', ''],
    'pr-message-header': ['black', ''],
    'pr-message-own-header': ['black,bold', ''],
    'focused-link': ['dark blue,bold', ''],
    'filename': ['dark cyan', ''],
    }

class Palette(object):
    def __init__(self, config):
        self.palette = {}
        self.palette.update(DEFAULT_PALETTE)
        self.update(config)

    def update(self, config):
        d = config.copy()
        if 'name' in d:
            del d['name']
        self.palette.update(d)

    def getPalette(self):
        ret = []
        for k,v in self.palette.items():
            ret.append(tuple([k]+v))
        return ret
