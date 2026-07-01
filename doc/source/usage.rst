Usage
-----

After installing Hubtty, you should be able to run it by invoking
``hubtty``.  If you installed it in a virtualenv, you can invoke it
without activating the virtualenv with ``/path/to/venv/bin/hubtty``
which you may wish to add to your shell aliases.  Use ``hubtty
--help`` to see a list of command line options available.

Once Hubtty is running, you will need to start by subscribing to some
repositories.  Use 'L' to list all of the repositories and then 's' to
subscribe to the ones you are interested in.  Hit 'L' again to shrink
the list to your subscribed repositories.

In general, pressing the F1 key will show help text on any screen, and
ESC will take you to the previous screen.

Hubtty works seamlessly offline or online.  All of the actions that it
performs are first recorded in a local database (in ``$XDG_DATA_HOME/hubtty/hubtty.db``
by default), and are then transmitted to Github.  If Hubtty is unable
to contact Github for any reason, it will continue to operate against
the local database, and once it re-establishes contact, it will
process any pending changes.

The status bar at the top of the screen displays the current number of
outstanding tasks that Hubtty must perform in order to be fully up to
date.  Some of these tasks are more complicated than others, and some
of them will end up creating new tasks (for instance, one task may be
to search for new pull requests in a repository which will then produce
5 new tasks if there are 5 new pull requests).

If Hubtty is offline, it will so indicate in the status bar.  It will
retry requests if needed, and will switch between offline and online
mode automatically.

To inspect what Hubtty is doing behind the scenes, press `Ctrl+T` to
open the sync task queue viewer.  It shows the currently running task
and all queued tasks grouped by priority.  The "Sync" indicator in the
header bar is also clickable and opens the same dialog.

If you review a pull request while offline with a positive vote, and someone
else leaves a negative vote on that pull request before Hubtty is able to
upload your review, Hubtty will detect the situation and mark the pull request
as "held" so that you may re-inspect the pull request and any new comments
before uploading the review.  The status bar will alert you to any held pull
requests and direct you to a list of them (the `F12` key by default).  When
viewing a pull request, the "held" flag may be toggled with the exclamation key
(`!`).  Once held, a pull request must be explicitly un-held in this manner for
your review to be uploaded.

If Hubtty encounters an error, this will also be indicated in the status bar.
You may wish to examine ``$XDG_DATA_HOME/hubtty/hubtty.log`` to see what the
error was.  In many cases, Hubtty can continue after encountering an error.
The error flag will be cleared when you leave the current screen.

Diff views support both side-by-side and unified layouts.  The default
can be set with the ``diff-view`` configuration option.  While viewing
a diff, press the `toggle diff view` key (`F2` in the default keymap,
`td` in the vi keymap) to switch between the two layouts at runtime
without changing the configuration file.

To select text (e.g., to copy to the clipboard), hold Shift while
selecting the text.

Commit Range Diffs (Interdiff)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Hubtty supports viewing diffs for arbitrary ranges of commits within a
pull request.  Press `D` in the pull request view or any diff view to
open the commit range dialog.  Select the starting ("From") and ending
("To") commits, then press Diff to display the combined diff for that
range.  Selecting "Base" as the starting point diffs from the PR base
to the chosen commit.

In the diff view, the "Commit (1/N)" label at the top is clickable and
also opens the commit range dialog.  Individual commit entries listed
below it can be clicked (or activated with Enter) to expand and show
the full commit message, rendered with markdown and commentlinks.
In single-commit view, the commit message is expanded by default.

The `diff-default` configuration option controls the default behavior
of the `d` key in the pull request view (see the configuration
documentation for details).

Generated Files
~~~~~~~~~~~~~~~

Hubtty automatically detects generated files and collapses their diffs
by default.  Generated files still appear in the diff view with their
filename and a ``[generated]`` marker, but the diff chunks are hidden.
In the pull request view, generated files are grouped into a single
summary row.

Press ``G`` (or ``t g`` in vi mode) in the diff view to toggle
expansion of generated file diffs.

Generated files are identified from three sources: ``.gitattributes``
entries with ``linguist-generated``, built-in heuristic patterns for
commonly generated files (lock files, protobuf output, minified assets,
etc.), and user-supplied glob patterns.  See the ``hide-generated-files``
and ``generated-files`` options in the configuration documentation for
details.
