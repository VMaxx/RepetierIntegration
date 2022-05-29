# Copyright (c) 2020 Aldo Hoeben / fieldOfView & Shane Bumpurs
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from .RepetierOutputDevice import RepetierOutputDevice

from UM.Signal import Signal, signalemitter
from UM.Application import Application
from UM.Logger import Logger
from UM.Util import parseBool

from PyQt6.QtCore import QTimer
import time
import json
import re
import base64
import os.path
import ipaddress

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel

##      This plugin handles the connection detection & creation of output device objects for Repetier-connected printers.
#       Zero-Conf is used to detect printers, which are saved in a dict.
#       If we discover an instance that has the same key as the active machine instance a connection is made.
@signalemitter
class RepetierOutputDevicePlugin(OutputDevicePlugin):
    def __init__(self) -> None:
        super().__init__()
        self._zero_conf = None
        self._browser = None
        self._instances = {}

        # Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
        self.addInstanceSignal.connect(self.addInstance)
        self.removeInstanceSignal.connect(self.removeInstance)
        Application.getInstance().globalContainerStackChanged.connect(self.reCheckConnections)

        # Load custom instances from preferences
        self._preferences = Application.getInstance().getPreferences()
        self._preferences.addPreference("Repetier/manual_instances", "{}")

        try:
            self._manual_instances = json.loads(self._preferences.getValue("Repetier/manual_instances"))
        except ValueError:
            self._manual_instances = {}
        if not isinstance(self._manual_instances, dict):
            self._manual_instances = {}

        self._name_regex = re.compile("Repetier instance (\".*\"\.|on )(.*)\.")

        self._keep_alive_timer = QTimer()
        self._keep_alive_timer.setInterval(2000)
        self._keep_alive_timer.setSingleShot(True)
        self._keep_alive_timer.timeout.connect(self._keepDiscoveryAlive)

    addInstanceSignal = Signal()
    removeInstanceSignal = Signal()
    instanceListChanged = Signal()

    ##  Start looking for devices on network.
    def start(self) -> None:
        self.startDiscovery()

    def startDiscovery(self):
        if self._browser:
            self._browser.cancel()
            self._browser = None
            self._printers = {}
        instance_keys = list(self._instances.keys())
        for key in instance_keys:
            self.removeInstance(key)

        # Add manual instances from preference
        for name, properties in self._manual_instances.items():
            additional_properties = {
                b"path": properties["path"].encode("utf-8"),
                b"useHttps": b"true" if properties.get("useHttps", False) else b"false",
                b'userName': properties.get("userName", "").encode("utf-8"),
                b'password': properties.get("password", "").encode("utf-8"),
				b'repetier_id': properties.get("repetier_id", "").encode("utf-8"),
                b"manual": b"true"
            } # These additional properties use bytearrays to mimick the output of zeroconf
            self.addInstance(name, properties["address"], properties["port"], additional_properties)

        self.instanceListChanged.emit()
    def _keepDiscoveryAlive(self) -> None:
        if not self._browser or not self._browser.is_alive():
            Logger.log("w", "Zeroconf discovery has died, restarting discovery of Repetier instances.")
            self.startDiscovery()

    def addManualInstance(self, name: str, address: str, port: int, path: str, useHttps: bool = False, userName: str = "", password: str = "", repetierid: str = "")-> None:
        self._manual_instances[name] = {"address": address, "port": port, "path": path, "useHttps": useHttps, "userName": userName, "password": password, "repetier_id":repetierid}
        self._preferences.setValue("Repetier/manual_instances", json.dumps(self._manual_instances))

        properties = { b"path": path.encode("utf-8"), b"useHttps": b"true" if useHttps else b"false", b'userName': userName.encode("utf-8"), b'password': password.encode("utf-8"), b"manual": b"true",b'repetier_id':repetierid.encode("utf-8")}

        if name in self._instances:
            self.removeInstance(name)

        self.addInstance(name, address, port, properties)
        self.instanceListChanged.emit()

    def removeManualInstance(self, name: str) -> None:
        if name in self._instances:
            self.removeInstance(name)
            self.instanceListChanged.emit()

        if name in self._manual_instances:
            self._manual_instances.pop(name, None)
            self._preferences.setValue("Repetier/manual_instances", json.dumps(self._manual_instances))

    ##  Stop looking for devices on network.
    def stop(self) -> None:
        self._keep_alive_timer.stop()
        if self._browser:
            self._browser.cancel()
        self._browser = None # type: Optional[ServiceBrowser]
        if self._zero_conf:
            self._zero_conf.close()

    def getInstances(self) -> Dict[str, Any]:
        return self._instances

    def getInstanceById(self, instance_id: str) -> Optional[RepetierOutputDevice]:
        instance = self._instances.get(instance_id, None)
        if instance:
            return instance
        Logger.log("w", "No instance found with id %s", instance_id)
        return None

    def reCheckConnections(self) -> None:
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        for key in self._instances:
            if key == global_container_stack.getMetaDataEntry("id"):
                api_key = global_container_stack.getMetaDataEntry("repetier_api_key", "")
                self._instances[key].setApiKey(api_key)
                self._instances[key].setShowCamera(parseBool(global_container_stack.getMetaDataEntry("repetier_show_camera", "true")))
                self._instances[key].connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
                self._instances[key].connect()
            else:
                if self._instances[key].isConnected():
                    self._instances[key].close()

    ##  Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
    def addInstance(self, name: str, address: str, port: int, properties: Dict[bytes, bytes]) -> None:
        instance = RepetierOutputDevice(name, address, port, properties)
        self._instances[instance.getId()] = instance
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack and instance.getId() == global_container_stack.getMetaDataEntry("id"):
            api_key = global_container_stack.getMetaDataEntry("repetier_api_key", "")
            instance.setApiKey(api_key)
            instance.setShowCamera(parseBool(global_container_stack.getMetaDataEntry("repetier_show_camera", "true")))
            instance.connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
            instance.connect()

    def removeInstance(self, name: str) -> None:
        instance = self._instances.pop(name, None)
        if instance:
            if instance.isConnected():
                instance.connectionStateChanged.disconnect(self._onInstanceConnectionStateChanged)
                instance.disconnect()

    ##  Handler for when the connection state of one of the detected instances changes
    def _onInstanceConnectionStateChanged(self, key: str) -> None:
        if key not in self._instances:
            return

        if self._instances[key].isConnected():
            self.getOutputDeviceManager().addOutputDevice(self._instances[key])
        else:
            self.getOutputDeviceManager().removeOutputDevice(key)


