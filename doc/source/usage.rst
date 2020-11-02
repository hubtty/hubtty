Usage
-----

After installing Hubtty, you should be able to run it by invoking
``hubtty``.  If you installed it in a virtualenv, you can invoke it
without activating the virtualenv with ``/path/to/venv/bin/hubtty``
which you may wish to add to your shell aliases.  Use ``hubtty
--help`` to see a list of command line options available.

Once Hubtty is running, you will need to start by subscribing to some
projects.  Use 'L' to list all of the projects and then 's' to
subscribe to the ones you are interested in.  Hit 'L' again to shrink
the list to your subscribed projects.

In general, pressing the F1 key will show help text on any screen, and
ESC will take you to the previous screen.

Hubtty works seamlessly offline or online.  All of the actions that it
performs are first recorded in a local database (in ``~/.hubtty.db``
by default), and are then transmitted to Github.  If Hubtty is unable
to contact Github for any reason, it will continue to operate against
the local database, and once it re-establishes contact, it will
process any pending changes.

The status bar at the top of the screen displays the current number of
outstanding tasks that Hubtty must perform in order to be fully up to
date.  Some of these tasks are more complicated than others, and some
of them will end up creating new tasks (for instance, one task may be
to search for new changes in a project which will then produce 5 new
tasks if there are 5 new changes).

If Hubtty is offline, it will so indicate in the status bar.  It will
retry requests if needed, and will switch between offline and online
mode automatically.

If you review a change while offline with a positive vote, and someone
else leaves a negative vote on that change in the same category before
Hubtty is able to upload your review, Hubtty will detect the situation
and mark the change as "held" so that you may re-inspect the change
and any new comments before uploading the review.  The status bar will
alert you to any held changes and direct you to a list of them (the
`F12` key by default).  When viewing a change, the "held" flag may be
toggled with the exclamation key (`!`).  Once held, a change must be
explicitly un-held in this manner for your review to be uploaded.

If Hubtty encounters an error, this will also be indicated in the
status bar.  You may wish to examine ~/.hubtty.log to see what the
error was.  In many cases, Hubtty can continue after encountering an
error.  The error flag will be cleared when you leave the current
screen.

To select text (e.g., to copy to the clipboard), hold Shift while
selecting the text.

Terminal Integration
~~~~~~~~~~~~~~~~~~~~

If you use rxvt-unicode, you can add something like the following to
``.Xresources`` to make Github URLs that are displayed in your
terminal (perhaps in an email or irc client) clickable links that open
in Hubtty::

  URxvt.perl-ext:           default,matcher
  URxvt.url-launcher:       sensible-browser
  URxvt.keysym.C-Delete:    perl:matcher:last
  URxvt.keysym.M-Delete:    perl:matcher:list
  URxvt.matcher.button:     1
  URxvt.matcher.pattern.1:  https:\/\/review.example.org/(\\#\/c\/)?(\\d+)[\w]*
  URxvt.matcher.launcher.1: hubtty --open $0

You will want to adjust the pattern to match the review site you are
interested in; multiple patterns may be added as needed.
