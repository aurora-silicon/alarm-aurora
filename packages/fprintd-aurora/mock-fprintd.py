import sys
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.bus.BusConnection(sys.argv[1])
name = dbus.service.BusName("net.reactivated.Fprint", bus)
manager = "net.reactivated.Fprint.Manager"
device = "net.reactivated.Fprint.Device"
device_path = "/net/reactivated/Fprint/Device/0"

class Manager(dbus.service.Object):
    @dbus.service.method(manager, out_signature="ao")
    def GetDevices(self):
        return [device_path]

class Device(dbus.service.Object):
    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return dbus.String("press")

    @dbus.service.method(device, in_signature="s", out_signature="as")
    def ListEnrolledFingers(self, user):
        return ["left-index-finger"]

    @dbus.service.method(device, in_signature="s")
    def Claim(self, user):
        pass

    @dbus.service.method(device)
    def Release(self):
        pass

    @dbus.service.method(device)
    def VerifyStop(self):
        pass

    @dbus.service.method(device, in_signature="s")
    def VerifyStart(self, finger):
        if sys.argv[2] == "match":
            GLib.timeout_add(200, self.match)

    @dbus.service.signal(device, signature="sb")
    def VerifyStatus(self, result, done):
        pass

    def match(self):
        self.VerifyStatus("verify-match", True)
        return False

manager_obj = Manager(name, "/net/reactivated/Fprint/Manager")
device_obj = Device(name, device_path)
print("ready", flush=True)
GLib.MainLoop().run()
