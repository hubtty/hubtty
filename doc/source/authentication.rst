Authentication
--------------

.. _authentication-config-file:

Configuration File
~~~~~~~~~~~~~~~~~~

Authentication information is stored in
``$XDG_CONFIG_HOME/hubtty/hubtty_auth.yaml``, usually
``~/.config/hubtty/hubtty_auth.yaml``.

The file has entries for the different servers the user has configured, with
each one having an authentication token.

Example:

.. code-block:: yaml

   github.com:
     token: <your_token>

OAuth Device Flow vs Personal Access Token
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When Hubtty can't find the authentication token for a given server it
implements the `Github OAuth device flow
<https://docs.github.com/en/free-pro-team@latest/developers/apps/authorizing-oauth-apps#device-flow>`_
to create an authentication token on the user's behalf. While convenient for
out of the box experience, this token comes with certain limitations when it
comes to posting content to Github: Hubtty can't submit reviews to repositories
for which the parent organization has enabled third-party application
restrictions without explicitly allowing Hubtty.

Personal access tokens don't have this limitation. It is thus recommended you
`create yourself a personal access token
<https://docs.github.com/en/free-pro-team@latest/github/authenticating-to-github/creating-a-personal-access-token>`_
with the following permissions:

* in the ``repo`` scope::

     repo:status
     public_repo

* in the ``admin:org`` scope::

     read:org

The newly generated token should then be saved in the :ref:`authentication
config file <authentication-config-file>` at
``$XDG_CONFIG_HOME/hubtty/hubtty_auth.yaml``.
