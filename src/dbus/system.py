# Copyright (C) 2018-2019 Endless Mobile, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Authors:
#       Joaquim Rocha <jrocha@endlessm.com>
#       Fabian Orccon <fabian@endlessm.com>
#
# Note: Copied & adapted from Clubhouse
#
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from hack_sound_server.utils.loggable import logger


class Desktop(GObject.Object):
    shell_proxy = None
    dbus_proxy = None

    @classmethod
    def get_dbus_proxy_async(klass, callback=None, *callback_args):
        def _on_dbus_proxy_ready(proxy, result):
            try:
                klass.dbus_proxy = proxy.new_finish(result)
            except GLib.Error as e:
                logger.warning("Error: Failed to get DBus proxy:", e.message)
                return

            if callable(callback):
                callback(klass.dbus_proxy, *callback_args)

        if klass.dbus_proxy is None:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION,
                                      0,
                                      None,
                                      "org.freedesktop.DBus",
                                      "/org/freedesktop/DBus",
                                      "org.freedesktop.DBus",
                                      None,
                                      _on_dbus_proxy_ready)
        elif callable(callback):
            callback(klass.dbus_proxy, *callback_args)

    @classmethod
    def get_shell_proxy_async(klass, callback=None, *callback_args):
        def _on_shell_proxy_ready(proxy, result):
            try:
                klass.shell_proxy = proxy.new_finish(result)
            except GLib.Error as e:
                logger.warning("Error: Failed to get Shell proxy:", e.message)
                return

            if callable(callback):
                callback(klass.dbus_proxy, *callback_args)

        if klass.shell_proxy is None:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION,
                                      0,
                                      None,
                                      "org.gnome.Shell",
                                      "/org/gnome/Shell",
                                      "org.gnome.Shell",
                                      None,
                                      _on_shell_proxy_ready)
        elif callable(callback):
            callback(klass.shell_proxy, *callback_args)

    @classmethod
    def get_foreground_app(klass):
        if klass.shell_proxy is None:
            logger.error("Cannot get property FocusedApp without a "
                         "Shell proxy")
            return None

        try:
            prop = klass.shell_proxy.get_cached_property("FocusedApp")
            return prop.unpack()
        except GLib.Error as e:
            logger.error(e)
        return None

    @classmethod
    def get_overview_active(klass):
        if klass.shell_proxy is None:
            logger.error("Cannot get property OverviewActive without a "
                         "Shell proxy")
            return None

        try:
            prop = klass.shell_proxy.get_cached_property("OverviewActive")
            return prop.unpack()
        except GLib.Error as e:
            logger.error(e)
        return None

    @classmethod
    def get_name_owner(klass, bus_name, callback, *callback_args):
        """
        Gets the unique name of the owner for a given bus name asynchronously.
        """
        if klass.dbus_proxy is None:
            logger.error("Cannot call GetNameOwner without a set DBus proxy")
            return

        def _on_get_name_owner_ready(unused_proxy, result, unused_arg):
            if isinstance(result, GLib.Error):
                name_owner = None
            else:
                name_owner = result
            callback(name_owner, *callback_args)
        try:
            proxy = klass.dbus_proxy
            proxy.GetNameOwner("(s)", bus_name,
                               result_handler=_on_get_name_owner_ready)
        except GLib.Error:
            pass
