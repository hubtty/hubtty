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

"""HTTP client for GitHub API communication."""

import json
import logging
import re
import time
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import requests

from .constants import TIMEOUT
from .exceptions import OfflineError, RestrictedError, RateLimitError

if TYPE_CHECKING:
    from hubtty.app import App


class HTTPClient:
    """Handles all HTTP communication with the GitHub API.

    This class provides methods for GET, POST, PUT, PATCH, and DELETE requests,
    with automatic pagination, rate limit handling, and response validation.
    """

    def __init__(self, app: 'App', user_agent: str, github_api_version: str) -> None:
        """Initialize the HTTP client.

        Args:
            app: The main application instance.
            user_agent: User-Agent string for HTTP requests.
            github_api_version: GitHub API version string.
        """
        self.app = app
        self.user_agent = user_agent
        self.github_api_version = github_api_version
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'token ' + app.config.token})
        self.log = logging.getLogger('hubtty.sync')
        # ETag cache: path -> (etag_value, cached_response)
        self._etag_cache: Dict[str, tuple] = {}

    def url(self, path: str) -> str:
        """Convert a path to a full URL.

        Args:
            path: API path (e.g., 'repos/owner/repo/pulls').

        Returns:
            Full URL including the API base.
        """
        return self.app.config.api_url + path

    def _base_headers(self) -> Dict[str, str]:
        """Return base headers for all requests."""
        return {
            'User-Agent': self.user_agent,
            'X-GitHub-Api-Version': self.github_api_version,
        }

    def checkResponse(self, response: requests.Response) -> None:
        """Validate an HTTP response and raise appropriate exceptions.

        Args:
            response: The HTTP response to check.

        Raises:
            OfflineError: If the server returned a 5xx error.
            RestrictedError: If OAuth app restrictions block access.
            RateLimitError: If rate limit is exceeded.
            Exception: For other 4xx status codes.
        """
        self.log.debug('HTTP status code: %d', response.status_code)

        # Handle 429 (rate limit exceeded)
        if response.status_code == 429:
            self._handle_rate_limit_response(response)

        # Handle 5xx (server errors) -- transient; treat as offline to retry
        if response.status_code >= 500:
            raise OfflineError(
                f"Received {response.status_code} status code"
            )

        # Handle 403 (forbidden)
        elif response.status_code == 403:
            # Check if it's a rate limit 403 first
            remaining = response.headers.get('X-RateLimit-Remaining')
            if remaining and int(remaining) == 0:
                self._handle_rate_limit_response(response)

            # Check for OAuth restriction
            result = re.search(
                r"the `([\w-]+)` organization has enabled OAuth App access restrictions",
                response.text
            )
            if result:
                org = result.group(1)
                error_msg = (
                    f"The '{org}' organization has enabled third-party restrictions "
                    f"and has not yet approved Hubtty. Your review will be submitted "
                    f"again next time Hubtty starts. Create yourself a Personal Access "
                    f"Token to continue using Hubtty with this organization: "
                    f"https://hubtty.readthedocs.io/en/latest/authentication.html"
                )
                self.app.error(error_msg)
                raise RestrictedError(
                    f"The '{org}' organization has enabled third-party restrictions "
                    f"and has not yet approved hubtty"
                )
            else:
                raise Exception(
                    f"Received {response.status_code} status code: {response.text}"
                )

        # Other error codes
        elif response.status_code >= 400:
            raise Exception(
                f"Received {response.status_code} status code: {response.text}"
            )

    def _handle_rate_limit_response(self, response: requests.Response) -> None:
        """Extract rate limit info and raise RateLimitError.

        Args:
            response: HTTP response with rate limit error.

        Raises:
            RateLimitError: Always raised with extracted rate limit context.
        """
        retry_after = response.headers.get('Retry-After')
        reset_time = response.headers.get('X-RateLimit-Reset')
        remaining = response.headers.get('X-RateLimit-Remaining')

        # Convert to integers if present
        retry_after_int = int(retry_after) if retry_after else None
        reset_time_int = int(reset_time) if reset_time else None
        remaining_int = int(remaining) if remaining else None

        # Determine if this is a secondary rate limit
        # Secondary: Has retry-after OR (remaining != 0)
        is_secondary = bool(retry_after) or (
            remaining_int is not None and remaining_int != 0
        )

        # Build informative error message
        parts = [f"Rate limit exceeded (HTTP {response.status_code})"]
        if retry_after_int:
            parts.append(f"retry-after: {retry_after_int}s")
        if reset_time_int:
            parts.append(f"reset: {reset_time_int}")
        if remaining_int is not None:
            parts.append(f"remaining: {remaining_int}")

        message = ", ".join(parts)

        raise RateLimitError(
            message,
            reset_time=reset_time_int,
            retry_after=retry_after_int,
            remaining=remaining_int,
            is_secondary=is_secondary,
            url=response.url,
        )

    def _should_handle_rate_limit(self, response: requests.Response) -> bool:
        """Check if response indicates rate limiting that should be handled.

        Args:
            response: HTTP response to check.

        Returns:
            True if we should wait and retry due to rate limiting.
        """
        # Case 1: Explicit rate limit response (429 or 403 with remaining=0)
        if response.status_code in [403, 429]:
            remaining_str = response.headers.get('X-RateLimit-Remaining')
            if remaining_str and int(remaining_str) == 0:
                return True
            if response.status_code == 429:
                return True

        # Case 2: Proactive rate limit (success but no quota left)
        if response.status_code == 200:
            remaining_str = response.headers.get('X-RateLimit-Remaining', '1')
            remaining = int(remaining_str)
            if remaining < 1:
                return True

        return False

    def _wait_for_rate_limit(self, response: requests.Response, url: str) -> None:
        """Wait for rate limit to reset before retrying.

        Follows GitHub's documented strategy:
        1. Use retry-after header if present (secondary rate limits)
        2. Use x-ratelimit-reset if present (primary rate limits)
        3. Otherwise wait 60 seconds (secondary rate limit fallback)

        Args:
            response: HTTP response with rate limit information.
            url: The URL being requested (for logging).
        """
        retry_after = response.headers.get('Retry-After')
        reset_time = response.headers.get('X-RateLimit-Reset')
        remaining = response.headers.get('X-RateLimit-Remaining', '?')

        # Strategy 1: Use retry-after header (secondary rate limits)
        if retry_after:
            sleep_time = int(retry_after)
            self.log.info(
                'Hit secondary rate limit on %s, retry-after: %d seconds (remaining: %s)',
                url,
                sleep_time,
                remaining,
            )
            time.sleep(sleep_time)
            return

        # Strategy 2: Use x-ratelimit-reset (primary rate limits)
        if reset_time:
            # Prevent negative sleep due to clock skew
            sleep_time = max(1, int(reset_time) - int(time.time()))
            self.log.info(
                'Hit primary rate limit on %s, reset in: %d seconds (remaining: %s)',
                url,
                sleep_time,
                remaining,
            )
            time.sleep(sleep_time)
            return

        # Strategy 3: Fallback for secondary rate limits without headers
        # Per GitHub docs: "wait for at least one minute before retrying"
        sleep_time = 60
        self.log.info(
            'Hit rate limit on %s with no timing headers, waiting %d seconds (remaining: %s)',
            url,
            sleep_time,
            remaining,
        )
        time.sleep(sleep_time)

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
        use_etag: bool = False,
    ) -> Any:
        """Perform a GET request with automatic pagination.

        When *use_etag* is ``True`` the client will:

        * Send ``If-None-Match`` with the cached ETag (if any) on the
          first page request.
        * On ``304 Not Modified`` return the previously-cached full
          response — this costs **zero** against the GitHub rate limit.
        * On ``200 OK`` store the new ETag and full (assembled) response
          in an in-memory cache for subsequent conditional requests.

        Args:
            path: API path to request.
            headers: Additional headers to include.
            response_callback: Custom response validator (defaults to checkResponse).
            use_etag: Enable conditional requests via ETag / If-None-Match.

        Returns:
            Parsed JSON response, or list of results if paginated.
        """
        url = self.url(path)
        ret = None
        done = False
        is_first_page = True
        first_page_etag = None

        default_headers = {
            **self._base_headers(),
            'Accept': 'application/vnd.github.v3+json',
            'Accept-Encoding': 'gzip',
        }

        if not response_callback:
            response_callback = self.checkResponse

        # Build per-page extra headers.  On the first page we may
        # include If-None-Match; subsequent pages never do.
        extra = dict(headers or {})
        cached_data = None
        if use_etag and path in self._etag_cache:
            cached_etag, cached_data = self._etag_cache[path]
            extra['If-None-Match'] = cached_etag

        while not done:
            self.log.debug('GET: %s', url)

            r = self.session.get(
                url,
                timeout=TIMEOUT,
                headers={**default_headers, **extra},
            )

            # CRITICAL: Check rate limits BEFORE calling response_callback
            # This allows us to handle rate limit responses before they become exceptions
            if self._should_handle_rate_limit(r):
                self._wait_for_rate_limit(r, url)
                continue  # Retry the request

            # Handle 304 Not Modified — return cached data immediately.
            # 304 responses don't count against the GitHub rate limit.
            if use_etag and r.status_code == 304 and is_first_page:
                self.log.debug('304 Not Modified (ETag cache hit): %s', path)
                return cached_data

            # Now validate response (will raise exceptions for non-rate-limit errors)
            response_callback(r)

            # Process successful response
            if r.status_code == 200:
                result = json.loads(r.text)
                # Unwrap dict-wrapped paginated responses so that
                # results from multiple pages are correctly merged
                # into a single flat list.
                if isinstance(result, dict) and 'items' in result:
                    result = result.get('items', [])
                elif isinstance(result, dict) and 'check_runs' in result:
                    result = result.get('check_runs', [])
                if isinstance(ret, list):
                    ret.extend(result)
                else:
                    ret = result
                if len(result) if isinstance(result, list) else result:
                    self.log.debug('200 OK, Received: %s', result)
                else:
                    self.log.debug('200 OK, No body.')

                # Capture ETag from first page
                if use_etag and is_first_page:
                    first_page_etag = r.headers.get('ETag')

            # After the first page, strip If-None-Match so that
            # subsequent pages are unconditional fetches.
            if is_first_page:
                is_first_page = False
                extra = dict(headers or {})

            # Check for pagination
            if 'next' in r.links.keys():
                url = r.links['next']['url']
            else:
                done = True

        # Store the fully-assembled result in the ETag cache.
        if use_etag and first_page_etag is not None:
            self._etag_cache[path] = (first_page_etag, ret)

        return ret

    def _mutating_request(
        self,
        method: str,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
        include_accept: bool = False,
    ) -> Optional[Any]:
        """Perform a mutating HTTP request (POST, PUT, PATCH, DELETE).

        Args:
            method: HTTP method ('post', 'put', 'patch', 'delete').
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
            include_accept: Whether to include Accept header.

        Returns:
            Parsed JSON response for POST, None for other methods.
        """
        url = self.url(path)
        default_headers = {
            **self._base_headers(),
            'Content-Type': 'application/json;charset=UTF-8',
        }
        if include_accept:
            default_headers['Accept'] = 'application/vnd.github.v3+json'

        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('%s: %s', method.upper(), url)
        self.log.debug('data: %s', data)

        # Retry loop for rate limiting (max 3 attempts)
        max_attempts = 3
        for attempt in range(max_attempts):
            request_method = getattr(self.session, method)
            r = request_method(
                url,
                data=json.dumps(data).encode('utf8'),
                timeout=TIMEOUT,
                headers={**default_headers, **(headers or {})}
            )

            # Check rate limits before validation
            if self._should_handle_rate_limit(r):
                if attempt < max_attempts - 1:
                    self._wait_for_rate_limit(r, url)
                    continue  # Retry
                else:
                    # Last attempt, let it raise
                    response_callback(r)

            # Validate response
            response_callback(r)
            self.log.debug('Received: %s', r.text)

            # Only POST returns parsed response
            if method == 'post' and r.text and len(r.text) > 0:
                try:
                    return json.loads(r.text)
                except Exception:
                    self.log.exception(
                        "Unable to parse result %s from post to %s", r.text, url
                    )
                    raise
            return None

        # Should never reach here
        return None

    def post(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> Optional[Any]:
        """Perform a POST request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.

        Returns:
            Parsed JSON response.
        """
        return self._mutating_request(
            'post', path, data, headers, response_callback, include_accept=True
        )

    def put(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a PUT request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('put', path, data, headers, response_callback)

    def patch(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a PATCH request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('patch', path, data, headers, response_callback)

    def delete(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a DELETE request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('delete', path, data, headers, response_callback)

    def query(self, query: str) -> Any:
        """Execute a GitHub search query.

        Args:
            query: Search query string.

        Returns:
            List of search results.
        """
        q = f'search/issues?per_page=100&q={query}'
        self.log.debug('Query: %s', q)
        return self.get(q)
