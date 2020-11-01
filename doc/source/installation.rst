Installation
------------

Debian
~~~~~~

Ghubtty is packaged in Debian and is currently available in:

 * unstable
 * testing
 * stable

You can install it with::

  apt-get install ghubtty

Fedora
~~~~~~

Ghubtty is packaged starting in Fedora 21.  You can install it with::

  yum install python-ghubtty

openSUSE
~~~~~~~~

Ghubtty is packaged for openSUSE 13.1 onwards.  You can install it via
`1-click install from the Open Build Service <http://software.opensuse.org/package/python-ghubtty>`_.

Arch Linux
~~~~~~~~~~

Ghubtty packages are available in the Arch User Repository packages. You
can get the package from::

  https://aur.archlinux.org/packages/python2-ghubtty/

Source
~~~~~~

When installing from source, it is recommended (but not required) to
install Ghubtty in a virtualenv.  To set one up::

  virtualenv ghubtty-env
  source ghubtty-env/bin/activate

To install the latest version from the cheeseshop::

  pip install ghubtty

To install from a git checkout::

  pip install .
