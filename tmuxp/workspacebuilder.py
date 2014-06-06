# -*- coding: utf8 -*-
"""Create a tmux workspace from a configuration :py:obj:`dict`.

tmuxp.workspacebuilder
~~~~~~~~~~~~~~~~~~~~~~

"""

from __future__ import absolute_import, division, print_function, \
    with_statement, unicode_literals

import os
import logging
import subprocess

from . import exc, config, Window, Pane, Session, Server
from ._compat import PY2, console_to_str
from .util import run_before_script

logger = logging.getLogger(__name__)


class WorkspaceBuilder(object):

    """Load workspace from session :py:obj:`dict`.

    Build tmux workspace from a configuration. Creates and names windows, sets
    options, splits windows into panes.

    The normal phase of loading is:

        1.  :term:`kaptan` imports json/yaml/ini. ``.get()`` returns python
            :class:`dict`::

                import kaptan
                sconf = kaptan.Kaptan(handler='yaml')
                sconf = sconfig.import_config(self.yaml_config).get()

            or from config file with extension::

                import kaptan
                sconf = kaptan.Kaptan()
                sconf = sconfig.import_config('path/to/config.yaml').get()

            kaptan automatically detects the handler from filenames.

        2.  :meth:`config.expand` sconf inline shorthand::

                from tmuxp import config
                sconf = config.expand(sconf)

        3.  :meth:`config.trickle` passes down default values from session
            -> window -> pane if applicable::

                sconf = config.trickle(sconf)

        4.  (You are here) We will create a :class:`Session` (a real
            ``tmux(1)`` session) and iterate through the list of windows, and
            their panes, returning full :class:`Window` and :class:`Pane`
            objects each step of the way::

                workspace = WorkspaceBuilder(sconf=sconf)

    It handles the magic of cases where the user may want to start
    a session inside tmux (when `$TMUX` is in the env variables).

    """

    def __init__(self, sconf, server=None):
        """Initialize workspace loading.

        :todo: initialize :class:`Session` from here, in ``self.session``.

        :param sconf: session config, includes a :py:obj:`list` of ``windows``.
        :type sconf: :py:obj:`dict`

        :param server:
        :type server: :class:`Server`

        """

        if not sconf:
            raise exc.EmptyConfigException('session configuration is empty.')

        # config.validate_schema(sconf)

        if isinstance(server, Server):
            self.server = server
        else:
            self.server = None

        self.sconf = sconf

    def build(self, session=None):
        """Build tmux workspace in session.

        Optionally accepts ``session`` to build with only session object.

        Without ``session``, it will use :class:`Server` at ``self.server``
        passed in on initialization to create a new Session object.

        :param session: - session to build workspace in
        :type session: :class:`Session`

        """

        if not session:
            if not self.server:
                raise exc.TmuxpException(
                    'WorkspaceBuilder.build requires server to be passed ' +
                    'on initialization, or pass in session object to here.'
                )

            if self.server.has_session(self.sconf['session_name']):
                self.session = self.server.findWhere(
                    {
                        'session_name': self.sconf['session_name']
                    }
                )
                raise exc.TmuxSessionExists(
                    'Session name %s is already running.' %
                    self.sconf['session_name']
                )
            else:
                session = self.server.new_session(
                    session_name=self.sconf['session_name']
                )

            assert(self.sconf['session_name'] == session.get('session_name'))
            assert(len(self.sconf['session_name']) > 0)

        self.session = session
        self.server = session.server

        self.server._list_sessions()
        assert self.server.has_session(session.get('session_name'))
        assert session.get('session_id')

        assert(isinstance(session, Session))

        focus = None

        if 'before_script' in self.sconf:
            try:
                run_before_script(self.sconf['before_script'])
            except Exception as e:
                self.session.kill_session()
                raise(e)

        for w, wconf in self.iter_create_windows(session):
            assert(isinstance(w, Window))

            focus_pane = None
            for p, pconf in self.iter_create_panes(w, wconf):
                assert(isinstance(p, Pane))
                p = p

                if 'layout' in wconf:
                    w.select_layout(wconf['layout'])

                if 'focus' in pconf and pconf['focus']:
                    focus_pane = p

            if 'focus' in wconf and wconf['focus']:
                focus = w

            if focus_pane:
                focus_pane.select_pane()

        if focus:
            focus.select_window()

    def iter_create_windows(self, s):
        """Return :class:`Window` iterating through session config dict.

        Generator yielding :class:`Window` by iterating through
        ``sconf['windows']``.

        Applies ``window_options`` to window.

        :param session: :class:`Session` from the config
        :rtype: tuple(:class:`Window`, ``wconf``)

        """
        for i, wconf in enumerate(self.sconf['windows'], start=1):
            if 'window_name' not in wconf:
                window_name = None
            else:
                window_name = wconf['window_name']

            w1 = None
            if i == int(1):  # if first window, use window 1
                w1 = s.attached_window()
                w1.move_window(99)
                pass

            sd = wconf['start_directory'] if 'start_directory' in wconf else None
            w = s.new_window(
                window_name=window_name,
                start_directory=sd,
                attach=False,  # do not move to the new window
                window_index=wconf.get('window_index', ''),
            )

            if i == int(1) and w1:  # if first window, use window 1
                w1.kill_window()
            assert(isinstance(w, Window))
            s.server._update_windows()
            if 'options' in wconf and isinstance(wconf['options'], dict):
                for key, val in wconf['options'].items():
                    w.set_window_option(key, val)

            if 'focus' in wconf and wconf['focus']:
                w.select_window()

            s.server._update_windows()

            yield w, wconf

    def iter_create_panes(self, w, wconf):
        """Return :class:`Pane` iterating through window config dict.

        Run ``shell_command`` with ``$ tmux send-keys``.

        :param w: window to create panes for
        :type w: :class:`Window`
        :param wconf: config section for window
        :type wconf: :py:obj:`dict`
        :rtype: tuple(:class:`Pane`, ``pconf``)

        """
        assert(isinstance(w, Window))

        pane_base_index = int(w.show_window_option('pane-base-index', g=True))

        for pindex, pconf in enumerate(wconf['panes'], start=pane_base_index):

            if pindex == int(pane_base_index):
                p = w.attached_pane()

            else:
                def get_pane_start_directory():

                    if 'start_directory' in pconf:
                        return pconf['start_directory']
                    elif 'start_directory' in wconf:
                        return wconf['start_directory']
                    else:
                        return None
                p = w.split_window(
                    attach=True,
                    start_directory=get_pane_start_directory(),
                )

            assert(isinstance(p, Pane))
            assert(int(p.get('pane_index')) == int(pindex))
            if 'layout' in wconf:
                w.select_layout(wconf['layout'])

            for cmd in pconf['shell_command']:
                p.send_keys(cmd)

            if 'focus' in pconf and pconf['focus']:
                w.select_pane(p['pane_id'])

            w.server._update_panes()

            yield p, pconf


def freeze(session):
    """Freeze live tmux session and Return session config :py:obj:`dict`.

    :param session: session object
    :type session: :class:`Session`
    :rtype: dict

    """
    sconf = {}

    sconf['session_name'] = session['session_name']

    sconf['windows'] = []
    for w in session.windows:
        wconf = {}
        wconf['options'] = w.show_window_options()
        wconf['window_name'] = w.get('window_name')
        wconf['layout'] = w.get('window_layout')
        wconf['panes'] = []
        if w.get('window_active', '0') == '1':
            wconf['focus']='true'

        # If all panes have same path, set 'start_directory' instead
        # of using 'cd' shell commands.
        pane_has_same_path = lambda p: (
            w.panes[0].get('pane_current_path') ==
            p.get('pane_current_path')
        )

        if (all(pane_has_same_path(p) for p in w.panes)):
            wconf['start_directory'] = w.panes[0].get('pane_current_path')

        for p in w.panes:
            pconf = {}
            pconf['shell_command'] = []

            if 'start_directory' not in wconf:
                pconf['shell_command'].append(
                    'cd ' + p.get('pane_current_path')
                )
                
            if p.get('pane_active', '0') == '1':
                pconf['focus']='true'

            current_cmd = p.get('pane_current_command')

            def filter_interpretters_and_shells():
                return (
                    current_cmd.startswith('-') or
                    any(
                        current_cmd.endswith(cmd)
                        for cmd in ['python', 'ruby', 'node']
                    )
                )

            if (filter_interpretters_and_shells()):
                current_cmd = None

            if current_cmd:
                if current_cmd == 'bash' or current_cmd == 'Python':
                    pconf['shell_command'].append([])
                else:
                    pconf['shell_command'].append(current_cmd)
            else:
                if not len(pconf['shell_command']):
                    pconf = 'pane'

            wconf['panes'].append(pconf)

        sconf['windows'].append(wconf)

    return sconf
