# Copyright (c) 2020 Aldo Hoeben / fieldOfView & Shane Bumpurs
# RepetierPlugin is released under the terms of the AGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from UM.Settings.ContainerRegistry import ContainerRegistry

from cura.CuraApplication import CuraApplication
from cura.MachineAction import MachineAction
from cura.Settings.CuraStackBuilder import CuraStackBuilder

from PyQt6.QtCore import pyqtSignal, pyqtProperty, pyqtSlot, QUrl, QObject, QTimer
from PyQt6.QtQml import QQmlComponent, QQmlContext
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtNetwork import QNetworkRequest, QNetworkAccessManager, QNetworkReply
from .NetworkReplyTimeout import NetworkReplyTimeout
from .RepetierOutputDevicePlugin import RepetierOutputDevicePlugin
from .RepetierOutputDevice import RepetierOutputDevice

QNetworkAccessManagerOperations = QNetworkAccessManager.Operation
QNetworkRequestKnownHeaders = QNetworkRequest.KnownHeaders
QNetworkRequestAttributes = QNetworkRequest.Attribute
QNetworkReplyNetworkErrors = QNetworkReply.NetworkError

import re
import os.path
import json
import base64

from typing import cast, Any, Tuple, Dict, List, Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from UM.Settings.ContainerInterface import ContainerInterface

catalog = i18nCatalog("cura")

class DiscoverRepetierAction(MachineAction):
    def __init__(self, parent: QObject = None) -> None:
        super().__init__("DiscoverRepetierAction", catalog.i18nc("@action", "Connect Repetier"))

        self._qml_url = "DiscoverRepetierAction.qml"

        self._application = CuraApplication.getInstance()
        self._network_plugin = None

        #   QNetwork manager needs to be created in advance. If we don't it can happen that it doesn't correctly
        #   hook itself into the event loop, which results in events never being fired / done.
        self._network_manager = QNetworkAccessManager()
        self._network_manager.finished.connect(self._onRequestFinished)
        self._printers = [""]
        self._groups = [""]
        self._printerlist_reply = None
        self._groupslist_reply = None
        self._settings_reply = None
        self._settings_reply_timeout = None # type: Optional[NetworkReplyTimeout]

        self._instance_supports_appkeys = False
        self._appkey_reply = None # type: Optional[QNetworkReply]
        self._appkey_request = None # type: Optional[QNetworkRequest]
        self._appkey_instance_id = ""

        self._appkey_poll_timer = QTimer()
        self._appkey_poll_timer.setInterval(500)
        self._appkey_poll_timer.setSingleShot(True)
        self._appkey_poll_timer.timeout.connect(self._pollApiKey)

        # Try to get version information from plugin.json
        plugin_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")
        try:
            with open(plugin_file_path) as plugin_file:
                plugin_info = json.load(plugin_file)
                self._plugin_version = plugin_info["version"]
        except:
            # The actual version info is not critical to have so we can continue
            self._plugin_version = "0.0"
            Logger.logException("w", "Could not get version information for the plugin")

        self._user_agent = ("%s/%s %s/%s" % (
            self._application.getApplicationName(),
            self._application.getVersion(),

            "RepetierIntegration",
            self._plugin_version
        )).encode()

        self._settings_instance = None

        self._instance_responded = False
        self._instance_in_error = False
        self._instance_api_key_accepted = False
        self._instance_supports_sd = False
        self._instance_supports_camera = False
        self._instance_webcamflip_y = False
        self._instance_webcamflip_x = False
        self._instance_webcamrot90 = False
        self._instance_webcamrot270 = False

        # Load keys cache from preferences
        self._preferences = self._application.getPreferences()
        self._preferences.addPreference("Repetier/keys_cache", "")

        try:
            self._keys_cache = json.loads(self._preferences.getValue("Repetier/keys_cache"))
        except ValueError:
            self._keys_cache = {}
        if not isinstance(self._keys_cache, dict):
            self._keys_cache = {}

        self._additional_components = None

        ContainerRegistry.getInstance().containerAdded.connect(self._onContainerAdded)
        self._application.engineCreatedSignal.connect(self._createAdditionalComponentsView)

    @pyqtProperty(str, constant=True)
    def pluginVersion(self) -> str:
        return self._plugin_version

    @pyqtSlot()
    def startDiscovery(self) -> None:
        if not self._plugin_id:
            return
        if not self._network_plugin:
            self._network_plugin = cast(RepetierOutputDevicePlugin, self._application.getOutputDeviceManager().getOutputDevicePlugin(self._plugin_id))
            if not self._network_plugin:
                return
            self._network_plugin.addInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.removeInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.instanceListChanged.connect(self._onInstanceDiscovery)
            self.instancesChanged.emit()
        else:
            # Restart bonjour discovery
            self._network_plugin.startDiscovery()

    def _onInstanceDiscovery(self, *args) -> None:
        self.instancesChanged.emit()

    @pyqtSlot(str)
    def removeManualInstance(self, name: str) -> None:
        if not self._network_plugin:
            return

        self._network_plugin.removeManualInstance(name)

    @pyqtSlot(str, str, int, str, bool, str, str,str)
    def setManualInstance(self, name, address, port, path, useHttps, userName, password,repetierid):
        if not self._network_plugin:
            return
        # This manual printer could replace a current manual printer
        self._network_plugin.removeManualInstance(name)
        
        self._network_plugin.addManualInstance(name, address, port, path, useHttps, userName, password, repetierid)

    def _onContainerAdded(self, container: "ContainerInterface") -> None:
        # Add this action as a supported action to all machine definitions
        if (
            isinstance(container, DefinitionContainer) and
            container.getMetaDataEntry("type") == "machine" and
            container.getMetaDataEntry("supports_usb_connection")
        ):

            self._application.getMachineActionManager().addSupportedAction(container.getId(), self.getKey())

    instancesChanged = pyqtSignal()
    appKeysSupportedChanged = pyqtSignal()
    appKeyReceived = pyqtSignal()
    instanceIdChanged = pyqtSignal()

    @pyqtProperty("QVariantList", notify = instancesChanged)
    def discoveredInstances(self) -> List[Any]:
        if self._network_plugin:
            instances = list(self._network_plugin.getInstances().values())
            instances.sort(key = lambda k: k.name)
            return instances
        else:
            return []

    @pyqtSlot(str)
    def setInstanceId(self, key: str) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if global_container_stack:
            global_container_stack.setMetaDataEntry("repetier_id", key)

        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

        self.instanceIdChanged.emit()

    @pyqtProperty(str, notify = instanceIdChanged)
    def instanceId(self) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return ""

        return global_container_stack.getMetaDataEntry("repetier_id", "")

    @pyqtSlot(str)
    @pyqtSlot(result = str)
    def getInstanceId(self) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            Logger.log("d", "getInstancdId - self._application.getGlobalContainerStack() returned nothing")
            return ""

        return global_container_stack.getMetaDataEntry("repetier_id", "")
    @pyqtSlot(str)
    def requestApiKey(self, instance_id: str) -> None:
        (instance, base_url, basic_auth_username, basic_auth_password) = self._getInstanceInfo(instance_id)
                                                                            
        if not base_url:
                                                                                                           
            return

        ## Request appkey
        self._appkey_instance_id = instance_id
        self._appkey_request = self._createRequest(
            QUrl(base_url + "plugin/appkeys/request"),
            basic_auth_username, basic_auth_password
        )
        self._appkey_request.setRawHeader(b"Content-Type", b"application/json")
        data = json.dumps({"app": "Cura"})
        self._appkey_reply = self._network_manager.post(self._appkey_request, data.encode())

    @pyqtSlot()
    def cancelApiKeyRequest(self) -> None:
        if self._appkey_reply:
            if self._appkey_reply.isRunning():
                self._appkey_reply.abort()
            self._appkey_reply = None

        self._appkey_request = None # type: Optional[QNetworkRequest]

        self._appkey_poll_timer.stop()

    def _pollApiKey(self) -> None:
        if not self._appkey_request:
            return
        self._appkey_reply = self._network_manager.get(self._appkey_request)

    @pyqtSlot(str)
    def probeAppKeySupport(self, instance_id: str) -> None:
        (instance, base_url, basic_auth_username, basic_auth_password) = self._getInstanceInfo(instance_id)
        if not base_url or not instance:
            return

        instance.getAdditionalData()

        self._instance_supports_appkeys = False
        self.appKeysSupportedChanged.emit()

        appkey_probe_request = self._createRequest(
            QUrl(base_url + "plugin/appkeys/probe"),
            basic_auth_username, basic_auth_password
        )
        self._appkey_reply = self._network_manager.get(appkey_probe_request)

    @pyqtSlot(str)
    def getPrinterList(self, base_url):        
        self._instance_responded = False
        Logger.log("d", "getPrinterList:base_url:" + base_url)
        url = QUrl( base_url + "printer/info")
        Logger.log("d", "getPrinterList:" + url.toString())
        settings_request = QNetworkRequest(url)        
        settings_request.setRawHeader("User-Agent".encode(), self._user_agent)
        self._printerlist_reply=self._network_manager.get(settings_request)
        return self._printers

    @pyqtSlot(str)
    def getModelGroups(self, base_url,slug,key):        
        self._instance_responded = False        
        url = QUrl( base_url + "/printer/api/" + slug +"?a=listModelGroups&apikey=" + key)
        Logger.log("d", "getModelGroups:" + url.toString())
        settings_request = QNetworkRequest(url)        
        settings_request.setRawHeader("User-Agent".encode(), self._user_agent)        
        self._grouplist_reply=self._network_manager.get(settings_request)
        return self._groups

    @pyqtSlot(str, str, str, str, str, str)
    def testApiKey(self,instance_id: str, base_url, api_key, basic_auth_username = "", basic_auth_password = "", work_id = "") -> None:
        (instance, base_url, basic_auth_username, basic_auth_password) = self._getInstanceInfo(instance_id)
        self._instance_responded = False
        self._instance_api_key_accepted = False
        self._instance_supports_sd = False
        self._instance_webcamflip_y = False
        self._instance_webcamflip_x = False
        self._instance_webcamrot90 = False
        self._instance_webcamrot270 = False
        self._instance_supports_camera = False
        self.selectedInstanceSettingsChanged.emit()
        if self._settings_reply:
            if self._settings_reply.isRunning():
                self._settings_reply.abort()
            self._settings_reply = None
        if self._settings_reply_timeout:
            self._settings_reply_timeout = None
        if ((api_key != "") and (api_key != None) and (work_id != "")):
            Logger.log("d", "Trying to access Repetier instance at %s with the provided API key." % base_url)
            Logger.log("d", "Using %s as work_id" % work_id)
            Logger.log("d", "Using %s as api_key" % api_key)
            url = QUrl(base_url + "/printer/api/" + work_id + "?a=getPrinterConfig&apikey=" + api_key)            
            settings_request = QNetworkRequest(url)
            settings_request.setRawHeader("x-api-key".encode(), api_key.encode())
            settings_request.setRawHeader("User-Agent".encode(), self._user_agent)
            if basic_auth_username and basic_auth_password:
                data = base64.b64encode(("%s:%s" % (basic_auth_username, basic_auth_password)).encode()).decode("utf-8")
                settings_request.setRawHeader("Authorization".encode(), ("Basic %s" % data).encode())
            self._settings_reply = self._network_manager.get(settings_request)
            self._settings_instance = instance
            self.getModelGroups(base_url,work_id,api_key)
        else:
            self.getPrinterList(base_url)

    @pyqtSlot(str)
    def setApiKey(self, api_key: str) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return
        global_container_stack.setMetaDataEntry("repetier_api_key", api_key)
        self._keys_cache[self.getInstanceId()] = api_key
        keys_cache = base64.b64encode(json.dumps(self._keys_cache).encode("ascii")).decode("ascii")
        self._preferences.setValue("Repetier/keys_cache", keys_cache)

        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

    #  Get the stored API key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(str, result=str)
    def getApiKey(self, instance_id: str) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return ""
        Logger.log("d", "APIKEY read %s" % global_container_stack.getMetaDataEntry("repetier_api_key",""))
        if instance_id == self.getInstanceId():
            api_key = global_container_stack.getMetaDataEntry("repetier_api_key","")
        else:
            api_key = self._keys_cache.get(instance_id, "")
        return api_key

    selectedInstanceSettingsChanged = pyqtSignal()

    @pyqtProperty(list)
    def getPrinters(self):
        return self._printers

    @pyqtProperty(list)
    def getGroups(self):
        return self._groups

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceResponded(self) -> bool:
        return self._instance_responded

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceInError(self) -> bool:
        return self._instance_in_error

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceApiKeyAccepted(self) -> bool:
        return self._instance_api_key_accepted

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceSupportsSd(self) -> bool:
        return self._instance_supports_sd

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceWebcamFlipY(self):
        return self._instance_webcamflip_y
    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceWebcamFlipX(self):
        return self._instance_webcamflip_x
    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceWebcamRot90(self):
        return self._instance_webcamrot90
    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceWebcamRot270(self):
        return self._instance_webcamrot270

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceSupportsCamera(self) -> bool:
        return self._instance_supports_camera

    @pyqtSlot(str, str, str)
    def setContainerMetaDataEntry(self, container_id: str, key: str, value: str) -> None:
        containers = ContainerRegistry.getInstance().findContainers(id = container_id)
        if not containers:
            Logger.log("w", "Could not set metadata of container %s because it was not found.", container_id)
            return

        containers[0].setMetaDataEntry(key, value)

    @pyqtSlot(bool)
    def applyGcodeFlavorFix(self, apply_fix: bool) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return

        gcode_flavor = "RepRap (Marlin/Sprinter)" if apply_fix else "UltiGCode"
        if global_container_stack.getProperty("machine_gcode_flavor", "value") == gcode_flavor:
            # No need to add a definition_changes container if the setting is not going to be changed
            return

        # Make sure there is a definition_changes container to store the machine settings
        definition_changes_container = global_container_stack.definitionChanges
        if definition_changes_container == ContainerRegistry.getInstance().getEmptyInstanceContainer():
            definition_changes_container = CuraStackBuilder.createDefinitionChangesContainer(
                global_container_stack, global_container_stack.getId() + "_settings")

        definition_changes_container.setProperty("machine_gcode_flavor", "value", gcode_flavor)

        # Update the has_materials metadata flag after switching gcode flavor
        definition = global_container_stack.getBottom()
        if (
            not definition or
            definition.getProperty("machine_gcode_flavor", "value") != "UltiGCode" or
            definition.getMetaDataEntry("has_materials", False)
        ):

            # In other words: only continue for the UM2 (extended), but not for the UM2+
            return

        has_materials = global_container_stack.getProperty("machine_gcode_flavor", "value") != "UltiGCode"

        material_container = global_container_stack.material

        if has_materials:
            global_container_stack.setMetaDataEntry("has_materials", True)

            # Set the material container to a sane default
            if material_container == ContainerRegistry.getInstance().getEmptyInstanceContainer():
                search_criteria = {
                    "type": "material",
                    "definition": "fdmprinter",
                    "id": global_container_stack.getMetaDataEntry("preferred_material")
                }
                materials = ContainerRegistry.getInstance().findInstanceContainers(**search_criteria)
                if materials:
                    global_container_stack.material = materials[0]
        else:
            # The metadata entry is stored in an ini, and ini files are parsed as strings only.
            # Because any non-empty string evaluates to a boolean True, we have to remove the entry to make it False.
            if "has_materials" in global_container_stack.getMetaData():
                global_container_stack.removeMetaDataEntry("has_materials")

            global_container_stack.material = ContainerRegistry.getInstance().getEmptyInstanceContainer()

        self._application.globalContainerStackChanged.emit()

    @pyqtSlot(str)
    def openWebPage(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _createAdditionalComponentsView(self) -> None:
        Logger.log("d", "Creating additional ui components for Repetier-connected printers.")

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RepetierComponents.qml")
        self._additional_components = self._application.createQmlComponent(path, {"manager": self})
        if not self._additional_components:
            Logger.log("w", "Could not create additional components for Repetier-connected printers.")
            return

        self._application.addAdditionalComponent(
            "monitorButtons",
            self._additional_components.findChild(QObject, "openRepetierButton")
        )

    def _onRequestFailed(self, reply: QNetworkReply) -> None:
#        if reply.operation() == QNetworkAccessManager.GetOperation:
        if reply.operation() == QNetworkAccessManagerOperations.GetOperation:
            if "api/settings" in reply.url().toString():  # Repetier settings dump from /settings:
                Logger.log("w", "Connection refused or timeout when trying to access Repetier at %s" % reply.url().toString())
                self._instance_in_error = True
                self.selectedInstanceSettingsChanged.emit()


    #  Handler for all requests that have finished.
    def _onRequestFinished(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReplyNetworkErrors.TimeoutError:
#        if reply.error() == QNetworkReply.TimeoutError:
            QMessageBox.warning(None,'Connection Timeout','Connection Timeout')
            return
#        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        http_status_code = reply.attribute(QNetworkRequestAttributes.HttpStatusCodeAttribute)
        if not http_status_code:
            #QMessageBox.warning(None,'Connection Attempt2',http_status_code)
            # Received no or empty reply
            Logger.log("d","Received no or empty reply")
            return

#        if reply.operation() == QNetworkAccessManager.GetOperation:
        if reply.operation() == QNetworkAccessManagerOperations.GetOperation:
            Logger.log("d",reply.url().toString())
            if "printer/info" in reply.url().toString():  # Repetier settings dump from printer/info:            
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                        Logger.log("d",reply.url().toString())
                        Logger.log("d", json_data)
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}

                    if "printers" in json_data:
                        Logger.log("d", "DiscoverRepetierAction: printers: %s",len(json_data["printers"]))
                        if len(json_data["printers"])>0:
                            self._printers = [""]
                            for printerinfo in json_data["printers"]:
                                 Logger.log("d", "Slug: %s",printerinfo["slug"])
                                 self._printers.append(printerinfo["slug"])

                    if "apikey" in json_data:
                        Logger.log("d", "DiscoverRepetierAction: apikey: %s",json_data["apikey"])
                        global_container_stack = self._application.getGlobalContainerStack()
                        if not global_container_stack:
                            return
                        global_container_stack.setMetaDataEntry("repetier_api_key", json_data["apikey"])
                        self._keys_cache[self.getInstanceId()] = json_data["apikey"]
                        keys_cache = base64.b64encode(json.dumps(self._keys_cache).encode("ascii")).decode("ascii")
                        self._preferences.setValue("Repetier/keys_cache", keys_cache)
                        self.appKeyReceived.emit()
            if "listModelGroups" in reply.url().toString():  # Repetier settings dump from listModelGroups:            
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                        Logger.log("d",reply.url().toString())
                        Logger.log("d", json_data)
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}
                    if "groupNames" in json_data:
                        Logger.log("d", "DiscoverRepetierAction: groupNames: %s",len(json_data["groupNames"]))
                        if len(json_data["groupNames"])>0:
                            self._groups = [""]
                            for gname in json_data["groupNames"]:
                                 Logger.log("d", "groupName: %s",gname)
                                 self._groups.append(gname)
        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

            if "getPrinterConfig" in reply.url().toString():  # Repetier settings dump from getPrinterConfig:            
                if http_status_code == 200:
                    Logger.log("d", "API key accepted by Repetier.")
                    self._instance_api_key_accepted = True

                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                        Logger.log("d",reply.url().toString())
                        Logger.log("d", json_data)
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}

                    if "general" in json_data and "sdcard" in json_data["general"]:
                        self._instance_supports_sd = json_data["general"]["sdcard"]

                    if "webcam" in json_data and "dynamicUrl" in json_data["webcam"]:
                        Logger.log("d", "DiscoverRepetierAction: Checking streamurl")
                        Logger.log("d", "DiscoverRepetierAction: %s", reply.url())
                        stream_url = json_data["webcam"]["dynamicUrl"].replace("127.0.0.1",re.findall( r'[0-9]+(?:\.[0-9]+){3}', reply.url().toString())[0])
                        Logger.log("d", "DiscoverRepetierAction: stream_url: %s",stream_url)
                        Logger.log("d", "DiscoverRepetierAction: reply_url: %s",reply.url())
                        if stream_url: #not empty string or None
                            self._instance_supports_camera = True
                    if "webcams" in json_data:
                        Logger.log("d", "DiscoverRepetierAction: webcams: %s",len(json_data["webcams"]))
                        if len(json_data["webcams"])>0:
                            if "dynamicUrl" in json_data["webcams"][0]:
                                Logger.log("d", "DiscoverRepetierAction: Checking streamurl")                                
                                Logger.log("d", "DiscoverRepetierAction: reply_url: %s",reply.url())								
                                stream_url = ""
                                #stream_url = json_data["webcams"][0]["dynamicUrl"].replace("127.0.0.1",re.findall( r'[0-9]+(?:\.[0-9]+){3}', reply.url().toString())[0])
                                if len(re.findall( r'[0-9]+(?:\.[0-9]+){3}', reply.url().toString()))>0:
                                     stream_url = json_data["webcams"][0]["dynamicUrl"].replace("127.0.0.1",re.findall( r'[0-9]+(?:\.[0-9]+){3}', reply.url().toString())[0])
                                Logger.log("d", "DiscoverRepetierAction: stream_url: %s",stream_url)
                                if stream_url: #not empty string or None
                                    self._instance_supports_camera = True
                elif http_status_code == 401:
                    Logger.log("d", "Invalid API key for Repetier.")
                    self._instance_api_key_accepted = False
                    self._instance_in_error = True

                self._instance_responded = True
                self.selectedInstanceSettingsChanged.emit()

    def _createRequest(self, url: str, basic_auth_username: str = "", basic_auth_password: str = "") -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
        request.setRawHeader(b"User-Agent", self._user_agent)

        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(("%s:%s" % (basic_auth_username, basic_auth_password)).encode()).decode("utf-8")
            request.setRawHeader(b"Authorization", ("Basic %s" % data).encode())

        # ignore SSL errors (eg for self-signed certificates)
        ssl_configuration = QSslConfiguration.defaultConfiguration()
        ssl_configuration.setPeerVerifyMode(QSslSocket.VerifyNone)
        request.setSslConfiguration(ssl_configuration)

        return request

    ##  Utility handler to base64-decode a string (eg an obfuscated API key), if it has been encoded before
    def _deobfuscateString(self, source: str) -> str:
        try:
            return base64.b64decode(source.encode("ascii")).decode("ascii")
        except UnicodeDecodeError:
            return source

    def _getInstanceInfo(self, instance_id: str) -> Tuple[Optional[RepetierOutputDevice], str, str, str]:
        if not self._network_plugin:
            return (None, "","","")
        instance = self._network_plugin.getInstanceById(instance_id)
        if not instance:
            return (None, "","","")

        return (instance, instance.baseURL, instance.getProperty("userName"), instance.getProperty("password"))