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

"""Thread-safe multi-priority queue for sync tasks."""

from collections import OrderedDict, deque
from threading import Condition
from typing import Any, List, Type, TypeVar

T = TypeVar('T')


class MultiQueue:
    """Thread-safe priority queue supporting multiple priority levels.

    Items are retrieved in priority order (lower priority value = higher priority).
    Duplicate items within the same priority level are rejected.
    """

    def __init__(self, priorities: List[int]) -> None:
        """Initialize the queue with the given priority levels.

        Args:
            priorities: List of priority levels, ordered from highest to lowest.
        """
        self.queues: OrderedDict[int, deque] = OrderedDict()
        for key in priorities:
            self.queues[key] = deque()
        self.condition = Condition()
        self.incomplete: List[Any] = []

    def qsize(self) -> int:
        """Return the total number of items in the queue, including incomplete."""
        with self.condition:
            count = sum(len(q) for q in self.queues.values())
            return count + len(self.incomplete)

    def put(self, item: T, priority: int) -> bool:
        """Add an item to the queue at the given priority.

        Args:
            item: The item to add.
            priority: The priority level for this item.

        Returns:
            True if the item was added, False if it was already in the queue.
        """
        with self.condition:
            if item not in self.queues[priority]:
                self.queues[priority].append(item)
                self.condition.notify()
                return True
            return False

    def get(self) -> T:
        """Remove and return the highest-priority item.

        Blocks until an item is available.

        Returns:
            The highest-priority item from the queue.
        """
        with self.condition:
            while True:
                for q in self.queues.values():
                    try:
                        ret = q.popleft()
                        self.incomplete.append(ret)
                        return ret
                    except IndexError:
                        pass
                self.condition.wait()

    def find(self, klass: Type[T], priority: int) -> List[T]:
        """Find all items of a given class at a specific priority level.

        Args:
            klass: The class type to search for.
            priority: The priority level to search in.

        Returns:
            List of items matching the given class.
        """
        results = []
        with self.condition:
            for item in self.queues[priority]:
                if isinstance(item, klass):
                    results.append(item)
        return results

    def complete(self, item: T) -> None:
        """Mark an item as complete, removing it from the incomplete list.

        Args:
            item: The item to mark as complete.
        """
        with self.condition:
            if item in self.incomplete:
                self.incomplete.remove(item)
