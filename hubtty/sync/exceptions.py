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

"""Exceptions for the sync module."""

from typing import Optional


class OfflineError(Exception):
    """Raised when the GitHub API is unreachable (e.g., 503 status)."""
    pass


class RestrictedError(Exception):
    """Raised when OAuth App access restrictions block access."""
    pass


class RateLimitError(Exception):
    """Raised when GitHub API rate limit is hit.

    Attributes:
        reset_time: Unix timestamp when the rate limit resets.
        retry_after: Seconds to wait before retrying (from Retry-After header).
        remaining: Number of requests remaining in the current quota.
        is_secondary: Whether this is a secondary rate limit.
        url: The URL that was rate limited.
    """

    def __init__(
        self,
        message: str,
        reset_time: Optional[int] = None,
        retry_after: Optional[int] = None,
        remaining: Optional[int] = None,
        is_secondary: bool = False,
        url: Optional[str] = None,
    ):
        """Initialize a RateLimitError.

        Args:
            message: Error message describing the rate limit.
            reset_time: Unix timestamp when rate limit resets.
            retry_after: Seconds to wait (from Retry-After header).
            remaining: Requests remaining in current quota.
            is_secondary: True if this is a secondary rate limit.
            url: The URL that triggered the rate limit.
        """
        super().__init__(message)
        self.reset_time = reset_time
        self.retry_after = retry_after
        self.remaining = remaining
        self.is_secondary = is_secondary
        self.url = url
