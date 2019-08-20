from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Settings.DefinitionContainer import DefinitionContainer
from cura.CuraApplication import CuraApplication

from UM.Settings.ContainerRegistry import ContainerRegistry
from cura.MachineAction import MachineAction
from cura.Settings.CuraStackBuilder import CuraStackBuilder

from PyQt5.QtCore import pyqtSignal, pyqtProperty, pyqtSlot, QUrl, QObject
from PyQt5.QtQml import QQmlComponent, QQmlContext
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtNetwork import QNetworkRequest, QNetworkAccessManager, QNetworkReply

import re
import os.path
import json
import base64

catalog = i18nCatalog("cura")

class DiscoverRepetierAction(MachineAction):
    def __init__(self, parent = None):
        super().__init__("DiscoverRepetierAction", catalog.i18nc("@action", "Connect Repetier"))

        self._qml_url = "DiscoverRepetierAction.qml"
        self._window = None
        self._context = None

        self._application = CuraApplication.getInstance()
        self._network_plugin = None

        #   QNetwork manager needs to be created in advance. If we don't it can happen that it doesn't correctly
        #   hook itself into the event loop, which results in events never being fired / done.
        self._network_manager = QNetworkAccessManager()
        self._network_manager.finished.connect(self._onRequestFinished)
        self._printers = [""]
        self._printerlist_reply = None
        self._settings_reply = None

        # Try to get version information from plugin.json
        plugin_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")
        try:
            with open(plugin_file_path) as plugin_file:
                plugin_info = json.load(plugin_file)
                plugin_version = plugin_info["version"]
        except:
            # The actual version info is not critical to have so we can continue
            plugin_version = "Unknown"
            Logger.logException("w", "Could not get version information for the plugin")

        self._user_agent = ("%s/%s %s/%s" % (
            self._application.getApplicationName(),
            self._application.getVersion(),

            "RepetierIntegration",
            self._application.getVersion()
        )).encode()


        self._instance_responded = False
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

    @pyqtSlot()
    def startDiscovery(self):
        if not self._network_plugin:
            self._network_plugin = self._application.getOutputDeviceManager().getOutputDevicePlugin(self._plugin_id)
            self._network_plugin.addInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.removeInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.instanceListChanged.connect(self._onInstanceDiscovery)
            self.instancesChanged.emit()
        else:
            # Restart bonjour discovery
            self._network_plugin.startDiscovery()

    def _onInstanceDiscovery(self, *args):
        self.instancesChanged.emit()

    @pyqtSlot(str)
    def removeManualInstance(self, name):
        if not self._network_plugin:
            return

        self._network_plugin.removeManualInstance(name)

    @pyqtSlot(str, str, int, str, bool, str, str,str)
    def setManualInstance(self, name, address, port, path, useHttps, userName, password,repetierid):
        # This manual printer could replace a current manual printer
        self._network_plugin.removeManualInstance(name)
        
        self._network_plugin.addManualInstance(name, address, port, path, useHttps, userName, password, repetierid)

    def _onContainerAdded(self, container):
        # Add this action as a supported action to all machine definitions
        if isinstance(container, DefinitionContainer) and container.getMetaDataEntry("type") == "machine" and container.getMetaDataEntry("supports_usb_connection"):
            self._application.getMachineActionManager().addSupportedAction(container.getId(), self.getKey())

    instancesChanged = pyqtSignal()

    @pyqtProperty("QVariantList", notify = instancesChanged)
    def discoveredInstances(self):
        if self._network_plugin:
            instances = list(self._network_plugin.getInstances().values())
            instances.sort(key = lambda k: k.name)
            return instances
        else:
            return []

    @pyqtSlot(str)
    def setInstanceId(self, key):
        global_container_stack = self._application.getGlobalContainerStack()
        if global_container_stack:
            global_container_stack.setMetaDataEntry("repetier_id", key)

        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

    @pyqtSlot(result = str)
    def getInstanceId(self) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            Logger.log("d", "getInstancdId - self._application.getGlobalContainerStack() returned nothing")
            return ""

        return global_container_stack.getMetaDataEntry("repetier_id", "")

    @pyqtSlot(str)
    def getPrinterList(self, base_url):        
        self._instance_responded = False
        url = QUrl("http://" + base_url + "/printer/info")
        Logger.log("d", "getPrinterList:" + url.toString())
        settings_request = QNetworkRequest(url)        
        settings_request.setRawHeader("User-Agent".encode(), self._user_agent)
        self._printerlist_reply=self._network_manager.get(settings_request)
        return self._printers

                
    @pyqtSlot(str, str, str, str, str)
    def testApiKey(self, base_url, api_key, basic_auth_username = "", basic_auth_password = "", work_id = ""):
        self._instance_responded = False
        self._instance_api_key_accepted = False
        self._instance_supports_sd = False
        self._instance_webcamflip_y = False
        self._instance_webcamflip_x = False
        self._instance_webcamrot90 = False
        self._instance_webcamrot270 = False
        self._instance_supports_camera = False
        self.selectedInstanceSettingsChanged.emit()        
        #global_container_stack = self._application.getGlobalContainerStack()
        #if global_container_stack:
        #     work_id = global_container_stack.getMetaDataEntry("repetier_id")
		
        if ((api_key != "") and (api_key !=None) and (work_id!="")):
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
        else:
            self.getPrinterList(base_url)
            if self._settings_reply:
                self._settings_reply.abort()
                self._settings_reply = None

    @pyqtSlot(str)
    def setApiKey(self, api_key):
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
    def getApiKey(self, instance_id):
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

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceResponded(self):
        return self._instance_responded

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceApiKeyAccepted(self):
        return self._instance_api_key_accepted

    @pyqtProperty(bool, notify = selectedInstanceSettingsChanged)
    def instanceSupportsSd(self):
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
    def instanceSupportsCamera(self):
        return self._instance_supports_camera

    @pyqtSlot(str, str, str)
    def setContainerMetaDataEntry(self, container_id, key, value):
        containers = ContainerRegistry.getInstance().findContainers(id = container_id)
        if not containers:
            UM.Logger.log("w", "Could not set metadata of container %s because it was not found.", container_id)
            return False

        containers[0].setMetaDataEntry(key, value)

    @pyqtSlot(bool)
    def applyGcodeFlavorFix(self, apply_fix):
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
        if definition.getProperty("machine_gcode_flavor", "value") != "UltiGCode" or definition.getMetaDataEntry("has_materials", False):
            # In other words: only continue for the UM2 (extended), but not for the UM2+
            return

        has_materials = global_container_stack.getProperty("machine_gcode_flavor", "value") != "UltiGCode"

        material_container = global_container_stack.material

        if has_materials:
            global_container_stack.setMetaDataEntry("has_materials", True)

            # Set the material container to a sane default
            if material_container == ContainerRegistry.getInstance().getEmptyInstanceContainer():
                search_criteria = { "type": "material", "definition": "fdmprinter", "id": global_container_stack.getMetaDataEntry("preferred_material")}
                materials = ContainerRegistry.getInstance().findInstanceContainers(**search_criteria)
                if materials:
                    global_container_stack.material = materials[0]
        else:
            # The metadata entry is stored in an ini, and ini files are parsed as strings only.
            # Because any non-empty string evaluates to a boolean True, we have to remove the entry to make it False.
            if "has_materials" in global_container_stack.getMetaData():
                global_container_stack.removeMetaDataEntry("has_materials")

            global_container_stack.material = ContainerRegistry.getInstance().getEmptyInstanceContainer()

        CuraApplication.getInstance().globalContainerStackChanged.emit()

    @pyqtSlot(str)
    def openWebPage(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def _createAdditionalComponentsView(self):
        Logger.log("d", "Creating additional ui components for Repetier-connected printers.")

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RepetierComponents.qml")
        self._additional_components = self._application.createQmlComponent(path, {"manager": self})
        if not self._additional_components:
            Logger.log("w", "Could not create additional components for Repetier-connected printers.")
            return

        self._application.addAdditionalComponent("monitorButtons", self._additional_components.findChild(QObject, "openRepetierButton"))


    #  Handler for all requests that have finished.
    def _onRequestFinished(self, reply):
        if reply.error() == QNetworkReply.TimeoutError:
            QMessageBox.warning(None,'Connection Timeout','Connection Timeout')
            return
        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if not http_status_code:
            #QMessageBox.warning(None,'Connection Attempt2',http_status_code)
            # Received no or empty reply
            Logger.log("d","Received no or empty reply")
            return

        if reply.operation() == QNetworkAccessManager.GetOperation:
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
                                stream_url = json_data["webcams"][0]["dynamicUrl"].replace("127.0.0.1",re.findall( r'[0-9]+(?:\.[0-9]+){3}', reply.url().toString())[0])
                                Logger.log("d", "DiscoverRepetierAction: stream_url: %s",stream_url)
                                Logger.log("d", "DiscoverRepetierAction: reply_url: %s",reply.url())
                                if stream_url: #not empty string or None
                                    self._instance_supports_camera = True
                elif http_status_code == 401:
                    Logger.log("d", "Invalid API key for Repetier.")
                    self._instance_api_key_accepted = False

                self._instance_responded = True
                self.selectedInstanceSettingsChanged.emit()

