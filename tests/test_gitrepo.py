# Copyright The Hubtty Authors.

import git
import pytest

from hubtty.gitrepo import Repo


@pytest.fixture
def repos(tmp_path):
    """Create a bare 'remote' repo and a cloned working repo.

    Returns (remote_path, working_path) as strings.
    """
    remote_path = str(tmp_path / "remote.git")
    working_path = str(tmp_path / "working")

    # Initialise bare remote with one commit on 'main'
    remote = git.Repo.init(remote_path, bare=True, initial_branch='main')
    clone = git.Repo.clone_from(remote_path, str(tmp_path / "setup_clone"))
    clone.index.commit("initial commit")
    clone.remote("origin").push("HEAD:refs/heads/main")
    clone.close()

    # Clone into the working repo that Repo() will wrap
    working = git.Repo.clone_from(remote_path, working_path)

    # Create branch pull/123/head and check it out in the working repo
    working.create_head("pull/123/head", "HEAD")
    working.git.checkout("pull/123/head")

    # Advance the remote so there's something new to fetch
    setup2 = git.Repo.clone_from(remote_path, str(tmp_path / "setup2"))
    setup2.create_head("pull/123/head", "HEAD")
    setup2.index.commit("second commit")
    setup2.remote("origin").push("HEAD:refs/heads/pull/123/head")
    setup2.close()

    remote.close()
    working.close()
    return remote_path, working_path


class TestFetchDetachesCheckedOutBranch:
    """Repo.fetch() detaches HEAD when the target branch is checked out."""

    def test_fetch_succeeds_when_branch_checked_out(self, repos):
        remote_path, working_path = repos
        repo = Repo(url=remote_path, path=working_path)

        # This would raise GitCommandError without the detach fix
        repo.fetch(remote_path, "+pull/123/head:pull/123/head")

        # HEAD should now be detached
        underlying = git.Repo(working_path)
        assert underlying.head.is_detached

    def test_fetch_leaves_head_alone_when_other_branch(self, repos):
        remote_path, working_path = repos

        # Switch to main so pull/123/head is NOT checked out
        underlying = git.Repo(working_path)
        underlying.git.checkout("main")
        underlying.close()

        repo = Repo(url=remote_path, path=working_path)
        repo.fetch(remote_path, "+pull/123/head:pull/123/head")

        # HEAD should still be on main, not detached
        underlying = git.Repo(working_path)
        assert not underlying.head.is_detached
        assert underlying.active_branch.name == "main"

    def test_fetch_with_list_refspec(self, repos):
        remote_path, working_path = repos
        repo = Repo(url=remote_path, path=working_path)

        repo.fetch(remote_path, ["+pull/123/head:pull/123/head"])

        underlying = git.Repo(working_path)
        assert underlying.head.is_detached

    def test_fetch_detached_head_no_error(self, repos):
        """Fetch works fine when HEAD is already detached."""
        remote_path, working_path = repos
        underlying = git.Repo(working_path)
        underlying.git.checkout("--detach")
        underlying.close()

        repo = Repo(url=remote_path, path=working_path)
        # Should not raise
        repo.fetch(remote_path, "+pull/123/head:pull/123/head")

        underlying = git.Repo(working_path)
        assert underlying.head.is_detached

    def test_fetch_refspec_without_colon(self, repos):
        """Fetch with a colon-less refspec doesn't incorrectly detach HEAD."""
        remote_path, working_path = repos
        underlying = git.Repo(working_path)
        underlying.git.checkout("main")
        underlying.close()

        repo = Repo(url=remote_path, path=working_path)
        repo.fetch(remote_path, "refs/heads/pull/123/head")

        underlying = git.Repo(working_path)
        assert not underlying.head.is_detached
        assert underlying.active_branch.name == "main"
