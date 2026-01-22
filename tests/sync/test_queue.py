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

"""Tests for MultiQueue thread-safe priority queue."""

import threading
import time

from hubtty.sync.queue import MultiQueue
from hubtty.sync.constants import HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY


class TestMultiQueuePriority:
    """Tests for priority ordering."""

    def test_priority_ordering(self):
        """Items are retrieved in priority order."""
        q = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        q.put("low", LOW_PRIORITY)
        q.put("high", HIGH_PRIORITY)
        q.put("normal", NORMAL_PRIORITY)

        assert q.get() == "high"
        q.complete("high")
        assert q.get() == "normal"
        q.complete("normal")
        assert q.get() == "low"

    def test_same_priority_fifo(self):
        """Items at the same priority are returned in FIFO order."""
        q = MultiQueue([NORMAL_PRIORITY])
        q.put("first", NORMAL_PRIORITY)
        q.put("second", NORMAL_PRIORITY)
        q.put("third", NORMAL_PRIORITY)

        assert q.get() == "first"
        q.complete("first")
        assert q.get() == "second"
        q.complete("second")
        assert q.get() == "third"


class TestMultiQueueDuplicates:
    """Tests for duplicate prevention."""

    def test_duplicate_prevention(self):
        """Duplicate items in same priority are rejected."""
        q = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY])
        assert q.put("item", HIGH_PRIORITY) is True
        assert q.put("item", HIGH_PRIORITY) is False
        assert q.qsize() == 1

    def test_same_item_different_priority_both_added(self):
        """Same item at different priorities is allowed."""
        q = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY])
        assert q.put("item", HIGH_PRIORITY) is True
        assert q.put("item", NORMAL_PRIORITY) is True
        assert q.qsize() == 2


class TestMultiQueueSize:
    """Tests for queue size tracking."""

    def test_qsize_empty(self):
        """Empty queue has size 0."""
        q = MultiQueue([NORMAL_PRIORITY])
        assert q.qsize() == 0

    def test_qsize_includes_incomplete(self):
        """qsize() includes items being processed."""
        q = MultiQueue([NORMAL_PRIORITY])
        q.put("item", NORMAL_PRIORITY)
        assert q.qsize() == 1

        item = q.get()  # Now in incomplete
        assert q.qsize() == 1  # Still counted

        q.complete(item)
        assert q.qsize() == 0

    def test_qsize_multiple_priorities(self):
        """qsize() counts items across all priorities."""
        q = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        q.put("high", HIGH_PRIORITY)
        q.put("normal", NORMAL_PRIORITY)
        q.put("low", LOW_PRIORITY)
        assert q.qsize() == 3


class TestMultiQueueFind:
    """Tests for find functionality."""

    def test_find_by_class(self):
        """find() returns items of specified class."""
        q = MultiQueue([NORMAL_PRIORITY])

        class TaskA:
            pass

        class TaskB:
            pass

        a1, a2 = TaskA(), TaskA()
        b1 = TaskB()

        q.put(a1, NORMAL_PRIORITY)
        q.put(b1, NORMAL_PRIORITY)
        q.put(a2, NORMAL_PRIORITY)

        found = q.find(TaskA, NORMAL_PRIORITY)
        assert len(found) == 2
        assert a1 in found
        assert a2 in found
        assert b1 not in found

    def test_find_empty_queue(self):
        """find() returns empty list on empty queue."""
        q = MultiQueue([NORMAL_PRIORITY])

        class TaskA:
            pass

        assert q.find(TaskA, NORMAL_PRIORITY) == []

    def test_find_wrong_priority(self):
        """find() only searches the specified priority."""
        q = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY])

        class TaskA:
            pass

        a1 = TaskA()
        q.put(a1, HIGH_PRIORITY)

        assert q.find(TaskA, NORMAL_PRIORITY) == []
        assert q.find(TaskA, HIGH_PRIORITY) == [a1]


class TestMultiQueueComplete:
    """Tests for completion handling."""

    def test_complete_removes_from_incomplete(self):
        """complete() removes item from incomplete list."""
        q = MultiQueue([NORMAL_PRIORITY])
        q.put("item", NORMAL_PRIORITY)
        item = q.get()
        assert q.qsize() == 1  # Still in incomplete

        q.complete(item)
        assert q.qsize() == 0

    def test_complete_nonexistent_item_safe(self):
        """complete() on non-existent item does not raise."""
        q = MultiQueue([NORMAL_PRIORITY])
        q.complete("nonexistent")  # Should not raise


class TestMultiQueueThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_put_get(self):
        """Queue handles concurrent put and get correctly."""
        q = MultiQueue([NORMAL_PRIORITY])
        results = []
        errors = []

        def producer():
            try:
                for i in range(50):
                    q.put(f"item-{i}", NORMAL_PRIORITY)
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                for _ in range(50):
                    item = q.get()
                    results.append(item)
                    q.complete(item)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Errors occurred: {errors}"
        assert len(results) == 50
        assert q.qsize() == 0

    def test_blocking_get(self):
        """get() blocks until item available."""
        q = MultiQueue([NORMAL_PRIORITY])
        result = []

        def delayed_put():
            time.sleep(0.05)
            q.put("delayed", NORMAL_PRIORITY)

        t = threading.Thread(target=delayed_put)
        t.start()

        start = time.time()
        item = q.get()  # Should block until put
        elapsed = time.time() - start
        result.append(item)
        t.join()

        assert result == ["delayed"]
        assert elapsed >= 0.04  # Should have waited
