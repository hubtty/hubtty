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

"""Account synchronization tasks."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..task import Task

if TYPE_CHECKING:
    from ..sync import Sync


@dataclass
class SyncOwnAccountTask(Task):
    """Sync the authenticated user's account information."""

    def run(self, sync: 'Sync') -> None:
        """Fetch and store the authenticated user's account info.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        remote = sync.get('user')
        sync.account_id = remote['id']
        with app.db.getSession() as session:
            account = session.getAccountByID(
                remote['id'],
                remote.get('name'),
                remote.get('login'),
                remote.get('email')
            )
            session.setOwnAccount(account)
        app.own_account_id = remote['id']


@dataclass
class SyncAccountTask(Task):
    """Sync a specific user's account information."""

    username: str

    def run(self, sync: 'Sync') -> None:
        """Fetch and store a user's account info by username.

        Args:
            sync: The Sync instance to use for API calls.
        """
        app = sync.app
        remote = sync.get('users/' + self.username)
        with app.db.getSession() as session:
            session.getAccountByID(
                remote['id'],
                remote.get('name'),
                remote.get('login'),
                remote.get('email')
            )
