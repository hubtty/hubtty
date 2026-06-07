# Copyright The Hubtty Authors.
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

"""Shared test fixtures for sync tests."""

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_app():
    """Create a mock App instance for testing."""
    app = Mock()
    app.config.api_url = 'https://api.github.com/'
    app.config.token = 'test-token'
    app.config.git_url = 'https://github.com/'
    app.config.expire_age = None

    # Mock database session context manager
    session_mock = MagicMock()
    app.db.getSession.return_value.__enter__ = Mock(return_value=session_mock)
    app.db.getSession.return_value.__exit__ = Mock(return_value=False)

    return app


@pytest.fixture
def mock_sync(mock_app):
    """Create a mock Sync instance for testing tasks."""
    sync = Mock()
    sync.app = mock_app
    sync.get = Mock(return_value={})
    sync.post = Mock(return_value={})
    sync.put = Mock()
    sync.patch = Mock()
    sync.delete = Mock()
    sync.query = Mock(return_value=[])
    sync.submitTask = Mock()
    return sync
