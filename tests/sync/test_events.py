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

"""Tests for sync update events."""

from hubtty.sync.events import (
    RepositoryAddedEvent,
    PullRequestAddedEvent,
    PullRequestUpdatedEvent,
)


class TestRepositoryAddedEvent:
    """Tests for RepositoryAddedEvent."""

    def test_creation(self):
        """Event is created with correct repository_key."""
        event = RepositoryAddedEvent(repository_key=123)
        assert event.repository_key == 123

    def test_repr(self):
        """repr includes repository_key."""
        event = RepositoryAddedEvent(repository_key=456)
        assert 'repository_key:456' in repr(event)


class TestPullRequestAddedEvent:
    """Tests for PullRequestAddedEvent."""

    def test_creation(self):
        """Event is created with correct keys."""
        event = PullRequestAddedEvent(repository_key=1, pr_key=2)
        assert event.repository_key == 1
        assert event.pr_key == 2

    def test_defaults(self):
        """New PR events have expected defaults."""
        event = PullRequestAddedEvent(repository_key=1, pr_key=2)
        assert event.review_flag_changed is True
        assert event.state_changed is True
        assert event.held_changed is False
        assert event.related_pr_keys == set()

    def test_repr(self):
        """repr includes key information."""
        event = PullRequestAddedEvent(repository_key=10, pr_key=20)
        r = repr(event)
        assert 'repository_key:10' in r
        assert 'pr_key:20' in r


class TestPullRequestUpdatedEvent:
    """Tests for PullRequestUpdatedEvent."""

    def test_creation(self):
        """Event is created with correct keys."""
        event = PullRequestUpdatedEvent(repository_key=3, pr_key=4)
        assert event.repository_key == 3
        assert event.pr_key == 4

    def test_defaults(self):
        """Updated PR events have expected defaults."""
        event = PullRequestUpdatedEvent(repository_key=1, pr_key=2)
        assert event.review_flag_changed is False
        assert event.state_changed is False
        assert event.held_changed is False
        assert event.related_pr_keys == set()

    def test_custom_flags(self):
        """Flags can be set on creation."""
        event = PullRequestUpdatedEvent(
            repository_key=1,
            pr_key=2,
            review_flag_changed=True,
            state_changed=True,
            held_changed=True,
        )
        assert event.review_flag_changed is True
        assert event.state_changed is True
        assert event.held_changed is True

    def test_repr(self):
        """repr includes flag information."""
        event = PullRequestUpdatedEvent(
            repository_key=10, pr_key=20, review_flag_changed=True
        )
        r = repr(event)
        assert 'repository_key:10' in r
        assert 'pr_key:20' in r
        assert 'review_flag_changed:True' in r
