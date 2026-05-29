# Sync Package

This package handles GitHub API synchronization for Hubtty.

## Structure

```
sync/
├── __init__.py          # Public exports (backward compatible)
├── constants.py         # Priority constants (HIGH/NORMAL/LOW_PRIORITY), TIMEOUT
├── exceptions.py        # OfflineError, RestrictedError, RateLimitError
├── queue.py             # MultiQueue - thread-safe priority queue
├── events.py            # UpdateEvent classes for UI notifications
├── task.py              # Base Task dataclass
├── http.py              # HTTPClient - GitHub API communication
├── sync.py              # Main Sync orchestrator
└── tasks/
    ├── account.py       # SyncOwnAccountTask, SyncAccountTask
    ├── repository.py    # Repository sync tasks
    ├── pull_request.py  # SyncPullRequestTask, SyncOutdatedPullRequestsTask
    ├── upload.py        # UploadReviewsTask, SetLabelsTask, SendMergeTask, etc.
    ├── maintenance.py   # PruneDatabaseTask, VacuumDatabaseTask
    └── repository_check.py  # CheckReposTask, CheckCommitsTask
```

## Design Decisions

### Dataclass-based Tasks

All tasks use Python dataclasses with automatic `__eq__` and `__repr__` generation:

```python
@dataclass
class SyncAccountTask(Task):
    username: str

    def run(self, sync: 'Sync') -> None:
        # implementation
```

The base `Task` class uses `kw_only=True` for the `priority` field, allowing subclasses to have positional fields.

### HTTP Method Consolidation

The `HTTPClient` class consolidates POST/PUT/PATCH/DELETE into a single `_mutating_request()` method to reduce duplication.

### Backward Compatibility

All public symbols are re-exported from `__init__.py`, so existing code using `from hubtty import sync` continues to work.

## Tests

Tests are in `tests/sync/`:

- `test_queue.py` - MultiQueue thread safety, priority ordering
- `test_task.py` - Task equality, completion, threading
- `test_http.py` - HTTP methods, response handling, pagination
- `test_events.py` - Event creation and defaults

Run tests:
```bash
uv run --group dev python -m pytest tests/sync/ -v
```

## Future Improvements

### 1. Decompose `_syncPullRequest`

The `SyncPullRequestTask._syncPullRequest` method is still ~300 lines. It could be split into focused helper functions:

- `fetch_pr_data()` - Fetch PR, commits, comments, reviews from API
- `fetch_commit_details()` - Fetch detailed commit info
- `fetch_commit_checks()` - Fetch CI status/checks
- `sync_pr_metadata()` - Update basic PR fields
- `sync_pr_labels()` - Add/remove labels
- `sync_commits()` - Create/update commits and files
- `sync_reviews()` - Process reviews and approvals
- `sync_inline_comments()` - Process inline code comments
- `cleanup_old_commits()` - Remove stale commits

These would go in `tasks/pull_request_helpers.py`.

### 2. Add Task Tests

Individual task classes need tests:

- `SyncPullRequestTask` - Most complex, highest priority
- `SyncRepositoryTask` - Repository sync logic
- `UploadReviewTask` - Review upload logic
- Other tasks as needed

### 3. Type Annotations

Some type annotations could be improved:
- Use `Protocol` for the `Sync` interface to break circular imports
- Add return type annotations to all methods

### 4. Error Handling

Consider adding:
- Retry logic for transient failures
- Better error messages for common failure modes
- Structured logging for debugging
