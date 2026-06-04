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

"""Base Task class for sync operations.

This module provides a dataclass-based Task base class that automatically
generates __eq__ and __repr__ methods for subclasses, reducing boilerplate.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional, TYPE_CHECKING
import logging
import time
import threading

from .constants import NORMAL_PRIORITY

if TYPE_CHECKING:
    from .sync import Sync


@dataclass(kw_only=True)
class Task:
    """Base class for all sync tasks.

    Subclasses should be decorated with @dataclass and define their
    identifying fields. The __eq__ and __repr__ methods are auto-generated
    based on these fields.

    The `priority` field is keyword-only with a default value, allowing
    subclasses to have positional fields without defaults.

    Example subclass:
        @dataclass
        class SyncAccountTask(Task):
            username: str

            def run(self, sync: 'Sync') -> None:
                # implementation
                pass

    Fields used for equality comparison should NOT have `compare=False`.
    The `priority` field is excluded from comparison by default.
    """

    # Priority is keyword-only with a default, so subclasses can have
    # positional fields without defaults
    priority: int = field(default=NORMAL_PRIORITY, compare=False, repr=False)
    delay: float = field(default=0, compare=False, repr=False)

    # Runtime state - not part of task identity
    succeeded: Optional[bool] = field(default=None, init=False, compare=False, repr=False)
    _event: threading.Event = field(
        default_factory=threading.Event, init=False, compare=False, repr=False
    )
    tasks: List['Task'] = field(default_factory=list, init=False, compare=False, repr=False)
    results: List[Any] = field(default_factory=list, init=False, compare=False, repr=False)
    followup: Optional['Task'] = field(default=None, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize the logger after dataclass initialization."""
        # Use object.__setattr__ in case the dataclass is frozen
        object.__setattr__(self, 'log', logging.getLogger('hubtty.sync'))
        # Compute the earliest time this task may run
        object.__setattr__(
            self, 'earliest_run',
            time.time() + self.delay if self.delay > 0 else 0
        )

    @property
    def log(self) -> logging.Logger:
        """Get the logger for this task."""
        return getattr(self, '_log', logging.getLogger('hubtty.sync'))

    @log.setter
    def log(self, value: logging.Logger) -> None:
        """Set the logger for this task."""
        object.__setattr__(self, '_log', value)

    def complete(self, success: bool) -> None:
        """Mark the task as complete with the given success status.

        Args:
            success: Whether the task completed successfully.
        """
        self.succeeded = success
        self._event.set()

    def wait(self, timeout: Optional[float] = None) -> Optional[bool]:
        """Wait for the task to complete.

        Args:
            timeout: Maximum time to wait in seconds, or None to wait forever.

        Returns:
            The success status if the task completed, or None if it timed out.
        """
        self._event.wait(timeout)
        return self.succeeded

    def run(self, sync: 'Sync') -> None:
        """Execute the task.

        Subclasses must implement this method.

        Args:
            sync: The Sync instance to use for API calls and task submission.

        Raises:
            NotImplementedError: If not overridden by subclass.
        """
        raise NotImplementedError("Subclasses must implement run()")
