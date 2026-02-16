# Copyright 2024 Hubtty Contributors
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

"""Lightweight profiling utilities for Hubtty.

Usage::

    from hubtty.perf import perf_log, PerfCounters

    # Time a block and log the result immediately:
    with perf_log("DiffView.refresh_data"):
        do_expensive_work()

    # Accumulate timings for repeated calls, then log a summary:
    counters = PerfCounters()
    for line in lines:
        with counters.count("_build_diff_line"):
            build_widget(line)
    counters.log_summary("DiffView._build_diff_widgets")

All output goes to the ``hubtty.perf`` logger at INFO level so it
can be independently enabled/disabled via logging configuration.
"""

import logging
import time
from contextlib import contextmanager

LOG = logging.getLogger("hubtty.perf")


@contextmanager
def perf_log(name):
    """Context manager that logs wall-clock time for a code block.

    Example output::

        [perf] DiffView.refresh_data: 1.234s
    """
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    LOG.info("[perf] %s: %.3fs", name, elapsed)


class PerfCounters:
    """Accumulate call counts and total time for repeated operations.

    Usage::

        counters = PerfCounters()
        for item in items:
            with counters.count("my_operation"):
                process(item)
        counters.log_summary("MyClass.my_method")
    """

    def __init__(self):
        self._counters = {}

    @contextmanager
    def count(self, name):
        """Time a single invocation and accumulate into *name*."""
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        entry = self._counters.get(name)
        if entry is None:
            entry = [0, 0.0]
            self._counters[name] = entry
        entry[0] += 1
        entry[1] += elapsed

    def log_summary(self, prefix=""):
        """Log all accumulated counters at INFO level.

        Example output::

            [perf]   _build_diff_line: 1532 calls, total 0.892s, avg 0.58ms
        """
        if prefix:
            prefix = prefix + " "
        for name, (calls, total) in sorted(self._counters.items()):
            avg_ms = (total / calls * 1000) if calls else 0
            LOG.info(
                "[perf]   %s%s: %d calls, total %.3fs, avg %.2fms",
                prefix,
                name,
                calls,
                total,
                avg_ms,
            )

    def reset(self):
        """Clear all accumulated counters."""
        self._counters.clear()
