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

"""Tests for base Task class and dataclass behavior."""

import pytest
from dataclasses import dataclass
import threading
import time

from hubtty.sync.task import Task
from hubtty.sync.constants import NORMAL_PRIORITY, HIGH_PRIORITY


@dataclass
class SimpleTask(Task):
    """Simple task with one field for testing."""

    name: str

    def run(self, sync):
        pass


@dataclass
class MultiFieldTask(Task):
    """Task with multiple fields for testing."""

    field1: str
    field2: int

    def run(self, sync):
        pass


class TestTaskEquality:
    """Tests for Task equality comparison."""

    def test_same_class_same_fields_equal(self):
        """Tasks with same class and fields are equal."""
        t1 = SimpleTask(name="test")
        t2 = SimpleTask(name="test")
        assert t1 == t2

    def test_same_class_different_fields_not_equal(self):
        """Tasks with different field values are not equal."""
        t1 = SimpleTask(name="test1")
        t2 = SimpleTask(name="test2")
        assert t1 != t2

    def test_different_class_not_equal(self):
        """Tasks of different classes are not equal."""
        t1 = SimpleTask(name="test")
        t2 = MultiFieldTask(field1="test", field2=1)
        assert t1 != t2

    def test_priority_excluded_from_equality(self):
        """Priority does not affect equality."""
        t1 = SimpleTask(name="test", priority=HIGH_PRIORITY)
        t2 = SimpleTask(name="test", priority=NORMAL_PRIORITY)
        assert t1 == t2

    def test_multi_field_equality(self):
        """Multi-field tasks compare all fields."""
        t1 = MultiFieldTask(field1="a", field2=1)
        t2 = MultiFieldTask(field1="a", field2=1)
        t3 = MultiFieldTask(field1="a", field2=2)

        assert t1 == t2
        assert t1 != t3


class TestTaskRepr:
    """Tests for Task repr."""

    def test_repr_includes_fields(self):
        """repr includes field values."""
        t = SimpleTask(name="test")
        r = repr(t)
        assert "name='test'" in r
        assert "SimpleTask" in r

    def test_repr_excludes_priority(self):
        """repr does not include priority."""
        t = SimpleTask(name="test", priority=HIGH_PRIORITY)
        r = repr(t)
        assert "priority" not in r

    def test_repr_multi_field(self):
        """repr includes all task fields."""
        t = MultiFieldTask(field1="abc", field2=42)
        r = repr(t)
        assert "field1='abc'" in r
        assert "field2=42" in r


class TestTaskCompletion:
    """Tests for Task completion handling."""

    def test_initial_state(self):
        """Task starts with succeeded=None."""
        t = SimpleTask(name="test")
        assert t.succeeded is None

    def test_complete_success(self):
        """complete(True) sets succeeded=True."""
        t = SimpleTask(name="test")
        t.complete(True)
        assert t.succeeded is True

    def test_complete_failure(self):
        """complete(False) sets succeeded=False."""
        t = SimpleTask(name="test")
        t.complete(False)
        assert t.succeeded is False

    def test_wait_returns_after_complete(self):
        """wait() returns after complete() is called."""
        t = SimpleTask(name="test")

        def complete_task():
            time.sleep(0.05)
            t.complete(True)

        thread = threading.Thread(target=complete_task)
        thread.start()

        result = t.wait(timeout=1.0)
        thread.join()

        assert result is True

    def test_wait_timeout(self):
        """wait() respects timeout."""
        t = SimpleTask(name="test")
        start = time.time()
        result = t.wait(timeout=0.05)
        elapsed = time.time() - start

        assert result is None  # Not completed yet
        assert elapsed < 0.2  # Didn't wait forever


class TestTaskLogger:
    """Tests for Task logger."""

    def test_has_logger(self):
        """Task has a logger."""
        t = SimpleTask(name="test")
        assert t.log is not None
        assert t.log.name == 'hubtty.sync'


class TestTaskLists:
    """Tests for Task task and result lists."""

    def test_tasks_list_empty(self):
        """Task starts with empty tasks list."""
        t = SimpleTask(name="test")
        assert t.tasks == []

    def test_results_list_empty(self):
        """Task starts with empty results list."""
        t = SimpleTask(name="test")
        assert t.results == []

    def test_tasks_list_independent(self):
        """Each task has its own tasks list."""
        t1 = SimpleTask(name="test1")
        t2 = SimpleTask(name="test2")

        t1.tasks.append("subtask")
        assert len(t1.tasks) == 1
        assert len(t2.tasks) == 0


class TestTaskRun:
    """Tests for Task run method."""

    def test_base_task_run_raises(self):
        """Base Task.run() raises NotImplementedError."""
        # Can't instantiate Task directly since it's abstract
        # but we can test a task that doesn't override run
        @dataclass
        class NoRunTask(Task):
            pass

        t = NoRunTask()
        with pytest.raises(NotImplementedError):
            t.run(None)
