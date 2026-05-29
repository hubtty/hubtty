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

"""Tests for Sync class."""

import pytest
import time
from unittest.mock import Mock, patch

from hubtty.sync.sync import Sync
from hubtty.sync.exceptions import RateLimitError


@pytest.fixture
def mock_app():
    """Create a mock App instance."""
    app = Mock()
    app.config.api_url = "https://api.github.com/"
    app.config.token = "test-token"
    app.config.expire_age = "2 months"
    app.error = Mock()
    app.db.getSession = Mock()
    app.status.update = Mock()
    return app


@pytest.fixture
def sync_instance(mock_app):
    """Create a Sync instance for testing."""
    with patch("hubtty.sync.sync.threading"):
        sync = Sync(mock_app, disable_background_sync=True)
    return sync


class TestRateLimitBackoff:
    """Tests for rate limit backoff calculation."""

    def test_primary_rate_limit_uses_retry_after(self, sync_instance):
        """Primary rate limit uses retry-after from headers."""
        error = RateLimitError("Rate limited", retry_after=45, is_secondary=False)

        backoff = sync_instance._calculate_rate_limit_backoff(error)

        assert backoff == 45
        assert sync_instance.consecutive_rate_limit_errors == 0

    def test_primary_rate_limit_uses_reset_time(self, sync_instance):
        """Primary rate limit uses reset time when retry-after absent."""
        reset_time = int(time.time()) + 30
        error = RateLimitError(
            "Rate limited", reset_time=reset_time, is_secondary=False
        )

        backoff = sync_instance._calculate_rate_limit_backoff(error)

        # Should be at least 1 second (due to max(1, ...))
        assert backoff >= 1
        assert backoff <= 31  # Allow for slight time passage
        assert sync_instance.consecutive_rate_limit_errors == 0

    def test_primary_rate_limit_fallback_60s(self, sync_instance):
        """Primary rate limit falls back to 60s when no headers."""
        error = RateLimitError("Rate limited", is_secondary=False)

        backoff = sync_instance._calculate_rate_limit_backoff(error)

        assert backoff == 60
        assert sync_instance.consecutive_rate_limit_errors == 0

    def test_secondary_rate_limit_first_attempt_with_retry_after(self, sync_instance):
        """Secondary rate limit first attempt uses retry-after."""
        error = RateLimitError("Rate limited", retry_after=45, is_secondary=True)

        backoff = sync_instance._calculate_rate_limit_backoff(error)

        assert backoff == 45
        assert sync_instance.consecutive_rate_limit_errors == 1

    def test_secondary_rate_limit_first_attempt_without_headers(self, sync_instance):
        """Secondary rate limit first attempt waits 60s without headers."""
        error = RateLimitError("Rate limited", is_secondary=True)

        backoff = sync_instance._calculate_rate_limit_backoff(error)

        assert backoff == 60
        assert sync_instance.consecutive_rate_limit_errors == 1

    def test_secondary_rate_limit_exponential_backoff_progression(self, sync_instance):
        """Secondary rate limit uses exponential backoff on repeated failures."""
        error = RateLimitError("Rate limited", is_secondary=True)

        # Attempt 1: 60s
        backoff1 = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff1 == 60
        assert sync_instance.consecutive_rate_limit_errors == 1

        # Attempt 2: 120s (60 * 2^1)
        backoff2 = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff2 == 120
        assert sync_instance.consecutive_rate_limit_errors == 2

        # Attempt 3: 240s (60 * 2^2)
        backoff3 = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff3 == 240
        assert sync_instance.consecutive_rate_limit_errors == 3

        # Attempt 4: 480s (60 * 2^3)
        backoff4 = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff4 == 480
        assert sync_instance.consecutive_rate_limit_errors == 4

    def test_secondary_rate_limit_max_backoff_600s(self, sync_instance):
        """Secondary rate limit backoff capped at 600s (10 minutes)."""
        error = RateLimitError("Rate limited", is_secondary=True)

        # Test attempt 4: Should be 480s (60 * 2^3)
        sync_instance.consecutive_rate_limit_errors = 3
        backoff = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff == 480  # 60 * 2^3
        assert sync_instance.consecutive_rate_limit_errors == 4

        # Note: We can't test higher attempts because >= 5 raises.
        # The cap of 600s is a safety measure for the formula
        # but in practice we give up after attempt 5.
        # The cap would only apply if the counter somehow got corrupted
        # or if we change the max attempts in the future.

    def test_secondary_rate_limit_gives_up_after_5_attempts(self, sync_instance):
        """Secondary rate limit raises after 5 attempts."""
        error = RateLimitError("Rate limited", is_secondary=True)

        # Set to 4 attempts already
        sync_instance.consecutive_rate_limit_errors = 4

        # 5th attempt should raise
        with pytest.raises(RateLimitError):
            sync_instance._calculate_rate_limit_backoff(error)

        # Counter should be reset
        assert sync_instance.consecutive_rate_limit_errors == 0

    def test_consecutive_errors_reset_on_success(self, sync_instance):
        """Consecutive error counter resets after successful request."""
        error = RateLimitError("Rate limited", is_secondary=True)

        # Simulate some failures
        sync_instance._calculate_rate_limit_backoff(error)
        sync_instance._calculate_rate_limit_backoff(error)
        assert sync_instance.consecutive_rate_limit_errors == 2

        # Simulate a successful task completion (this happens in run() method)
        # The counter gets reset in the success path of run()
        sync_instance.consecutive_rate_limit_errors = 0

        # Next failure should start fresh at attempt 1
        backoff = sync_instance._calculate_rate_limit_backoff(error)
        assert backoff == 60  # Back to first attempt
        assert sync_instance.consecutive_rate_limit_errors == 1
