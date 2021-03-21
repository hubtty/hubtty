Contributing
============

To browse the latest code, see: https://github.com/hubtty/hubtty
To clone the latest code, use `git clone https://github.com/hubtty/hubtty.git`

Bugs are handled at: https://github.com/hubtty/hubtty/issues

Philosophy
----------

Hubtty is based on the following precepts which should inform changes
to the program:

* Support large numbers of review requests across large numbers of
  projects.  Help the user prioritize those reviews.

* Adopt a news/mailreader-like workflow in support of the above.
  Being able to subscribe to projects, mark reviews as "read" without
  reviewing, etc, are all useful concepts to support a heavy review
  load (they have worked extremely well in supporting people who
  read/write a lot of mail/news).

* Support off-line use.  Hubtty should be completely usable off-line
  with reliable syncing between local data and Github when a
  connection is available (just like git or mail or news).

* Ample use of color.  Unlike a web interface, a good text interface
  relies mostly on color and precise placement rather than whitespace
  and decoration to indicate to the user the purpose of a given piece
  of information.  Hubtty should degrade well to 16 colors, but more
  (88 or 256) may be used.

* Keyboard navigation (with easy-to-remember commands) should be
  considered the primary mode of interaction.  Mouse interaction
  should also be supported.

* The navigation philosophy is a stack of screens, where each
  selection pushes a new screen onto the stack, and ESC pops the
  screen off.  This makes sense when drilling down to a change from
  lists, but also supports linking from change to change (via commit
  messages or comments) and navigating back intuitive (it matches
  expectations set by the web browsers).
