# Copyright (c) 2020 Aldo Hoeben / fieldOfView & Shane Bumpurs
# RepetierPlugin is released under the terms of the AGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Signal import signalemitter
from UM.Message import Message
from UM.Util import parseBool
from UM.Mesh.MeshWriter import MeshWriter
from UM.PluginRegistry import PluginRegistry

from cura.CuraApplication import CuraApplication

from cura.PrinterOutput.PrinterOutputDevice import PrinterOutputDevice, ConnectionState
from cura.PrinterOutput.NetworkedPrinterOutputDevice import NetworkedPrinterOutputDevice
from cura.PrinterOutput.Models.PrinterOutputModel import PrinterOutputModel
from cura.PrinterOutput.Models.PrintJobOutputModel import PrintJobOutputModel

from cura.PrinterOutput.GenericOutputController import GenericOutputController

from PyQt5.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkRequest, QNetworkAccessManager
from PyQt5.QtNetwork import QNetworkReply, QSslConfiguration, QSslSocket
from PyQt5.QtCore import QUrl, QTimer, pyqtSignal, pyqtProperty, pyqtSlot, QCoreApplication
from PyQt5.QtGui import QImage, QDesktopServices

import json
import os.path
import re
import datetime
from time import time
import base64
from io import StringIO, BytesIO
from enum import IntEnum

from typing import cast, Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from UM.Scene.SceneNode import SceneNode #For typing.
    from UM.FileHandler.FileHandler import FileHandler #For typing.

i18n_catalog = i18nCatalog("cura")

#  The current processing state of the backend.
#   This shadows PrinterOutputDevice.ConnectionState because its spelling changed
#   between Cura 4.0 beta 1 and beta 2
class UnifiedConnectionState(IntEnum):
    try:
        Closed = ConnectionState.Closed
        Connecting = ConnectionState.Connecting
        Connected = ConnectionState.Connected
        Busy = ConnectionState.Busy
        Error = ConnectionState.Error
    except AttributeError:
        Closed = ConnectionState.closed          # type: ignore
        Connecting = ConnectionState.connecting  # type: ignore
        Connected = ConnectionState.connected    # type: ignore
        Busy = ConnectionState.busy              # type: ignore
        Error = ConnectionState.error            # type: ignore
#  Repetier connected (wifi / lan) printer using the Repetier API
@signalemitter
class RepetierOutputDevice(NetworkedPrinterOutputDevice):
    def __init__(self, instance_id: str, address: str, port: int, properties: dict, **kwargs) -> None:
        super().__init__(device_id = instance_id, address = address, properties = properties, **kwargs)

        self._address = address
        self._port = port
        self._path = properties.get(b"path", b"/").decode("utf-8")
        if self._path[-1:] != "/":
            self._path += "/"
        self._id = instance_id
        self._repetier_id = properties.get(b"repetier_id", b"").decode("utf-8")
        self._properties = properties  # Properties dict as provided by zero conf

        self._gcode_stream = StringIO()

        self._auto_print = True
        self._forced_queue = False

        # We start with a single extruder, but update this when we get data from Repetier
        self._number_of_extruders_set = False
        self._number_of_extruders = 1

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

        self._user_agent_header = "User-Agent".encode()
        self._user_agent = ("%s/%s %s/%s" % (
            CuraApplication.getInstance().getApplicationName(),
            CuraApplication.getInstance().getVersion(),
            "RepetierIntegration",
            plugin_version
        ))
        Logger.log("d", "Repetier_ID: %s", self._repetier_id)
        self._api_prefix = "printer/api/" + self._repetier_id
        self._job_prefix = "printer/job/" + self._repetier_id
        self._save_prefix = "printer/model/" + self._repetier_id
        self._api_header = "x-api-key".encode()
        self._api_key = b""

        self._protocol = "https" if properties.get(b'useHttps') == b"true" else "http"
        self._base_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, self._path)
        self._api_url = self._base_url + self._api_prefix
        self._job_url = self._base_url + self._job_prefix
        self._save_url = self._base_url + self._save_prefix

        self._basic_auth_header = "Authorization".encode()
        self._basic_auth_data = None
        basic_auth_username = properties.get(b"userName", b"").decode("utf-8")
        basic_auth_password = properties.get(b"password", b"").decode("utf-8")
        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(("%s:%s" % (basic_auth_username, basic_auth_password)).encode()).decode("utf-8")
            self._basic_auth_data = ("basic %s" % data).encode()

        self._monitor_view_qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MonitorItem.qml")

        name = self._id
        matches = re.search(r"^\"(.*)\"\._Repetier\._tcp.local$", name)
        if matches:
            name = matches.group(1)
        Logger.log("d", "NAME IS: %s", name)
        Logger.log("d", "ADDRESS IS: %s", self._address)
        self.setPriority(2) # Make sure the output device gets selected above local file output
        self.setName(name)
        self.setShortDescription(i18n_catalog.i18nc("@action:button", "Print with Repetier"))
        self.setDescription(i18n_catalog.i18nc("@properties:tooltip", "Print with Repetier"))
        self.setIconName("print")
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to Repetier on {0}").format(self._repetier_id))

        self._post_reply = None

        self._progress_message = None # type: Union[None, Message]
        self._error_message = None # type: Union[None, Message]
        self._connection_message = None # type: Union[None, Message]

        self._queued_gcode_commands = [] # type: List[str]
        self._queued_gcode_timer = QTimer()
        self._queued_gcode_timer.setInterval(0)
        self._queued_gcode_timer.setSingleShot(True)
        self._queued_gcode_timer.timeout.connect(self._sendQueuedGcode)

        self._update_timer = QTimer()
        self._update_timer.setInterval(2000)  # TODO; Add preference for update interval
        self._update_timer.setSingleShot(False)
        self._update_timer.timeout.connect(self._update)

        self._show_camera = True
        self._camera_mirror = False
        self._camera_rotation = 0
        self._camera_url = ""
        self._camera_shares_proxy = False

        self._sd_supported = False

        self._plugin_data = {} #type: Dict[str, Any]

        self._output_controller = GenericOutputController(self)
        
    def getProperties(self) -> Dict[bytes, bytes]:
        return self._properties

    @pyqtSlot(str, result = str)
    def getProperty(self, key: str) -> str:
        key_b = key.encode("utf-8")
        if key_b in self._properties:
            return self._properties.get(key_b, b"").decode("utf-8")
        else:
            return ""

    #  Get the unique key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(result = str)
    def getId(self) -> str:
        return self._id

    #  Set the API key of this Repetier instance
    def setApiKey(self, api_key: str) -> None:
        self._api_key = api_key.encode()

    #  Name of the instance (as returned from the zeroConf properties)
    @pyqtProperty(str, constant = True)
    def name(self) -> str:
        return self._name

    #  Name of the printer in repetier
    additionalDataChanged = pyqtSignal()
    @pyqtProperty(str, notify=additionalDataChanged)
    def RepetierVersion(self) -> str:
        return self._repetier_version
	
    @pyqtProperty(str, constant = True)
    def repetier_id(self) -> str:
        return self._repetier_id

    def setRepetierid(self, strid: str) -> None:
        Logger.log("d", strid)
        self._repetier_id=strid
        
    #  Version (as returned from the zeroConf properties)
    @pyqtProperty(str, constant=True)
    def repetierVersion(self) -> str:
        return self._properties.get(b"version", b"").decode("utf-8")

    # IPadress of this instance
    @pyqtProperty(str, constant=True)
    def ipAddress(self) -> str:
        return self._address

    # IP address of this instance
    @pyqtProperty(str, notify=additionalDataChanged)
    def address(self) -> str:
        return self._address

    # port of this instance
    @pyqtProperty(int, constant=True)
    def port(self) -> int:
        return self._port

    # path of this instance
    @pyqtProperty(str, constant=True)
    def path(self) -> str:
        return self._path

    # absolute url of this instance
    @pyqtProperty(str, constant=True)
    def baseURL(self) -> str:
        return self._base_url

    cameraOrientationChanged = pyqtSignal()

    @pyqtProperty("QVariantMap", notify = cameraOrientationChanged)
    def cameraOrientation(self) -> Dict[str, Any]:
        return {
            "mirror": self._camera_mirror,
            "rotation": self._camera_rotation,
        }

    cameraUrlChanged = pyqtSignal()

    @pyqtProperty("QUrl", notify = cameraUrlChanged)
    def cameraUrl(self) -> QUrl:
        return QUrl(self._camera_url)

    def setShowCamera(self, show_camera: bool) -> None:
        if show_camera != self._show_camera:
            self._show_camera = show_camera
            self.showCameraChanged.emit()

    showCameraChanged = pyqtSignal()

    @pyqtProperty(bool, notify = showCameraChanged)
    def showCamera(self) -> bool:
        return self._show_camera

    def _update(self) -> None:
        # Request 'general' printer data
        self.get("stateList", self._onRequestFinished)
        # Request print_job data
        self.get("listPrinter", self._onRequestFinished)
        # Request print_job data
        #self.get("getPrinterConfig", self._onRequestFinished)



    def close(self) -> None:
        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Closed))
        if self._progress_message:
            self._progress_message.hide()
        if self._error_message:
            self._error_message.hide()
        self._update_timer.stop()

    def requestWrite(self, nodes: List["SceneNode"], file_name: Optional[str] = None, limit_mimetypes: bool = False, file_handler: Optional["FileHandler"] = None, **kwargs: str) -> None:
        self.writeStarted.emit(self)

        # Get the g-code through the GCodeWriter plugin
        # This produces the same output as "Save to File", adding the print settings to the bottom of the file
        gcode_writer = cast(MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter"))
        if not gcode_writer.write(self._gcode_stream, None):
            Logger.log("e", "GCodeWrite failed: %s" % gcode_writer.getInformation())
            return
        self.startPrint()

    ##  Start requesting data from the instance
    def connect(self) -> None:
        self._createNetworkManager()

        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connecting))
        self._update()  # Manually trigger the first update, as we don't want to wait a few secs before it starts.
        Logger.log("d", "Connection with instance %s with url %s started", self._repetier_id, self._base_url)
        self._update_timer.start()

        self._last_response_time = None
        self._setAcceptsCommands(False)
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connecting to Repetier on {0}").format(self._base_url))

        ## Request 'settings' dump
        self.get("getPrinterConfig", self._onRequestFinished)
        self._settings_reply = self._manager.get(self._createEmptyRequest("getPrinterConfig"))
        self._settings_reply = self._manager.get(self._createEmptyRequest("stateList"))

    ##  Stop requesting data from the instance
    def disconnect(self) -> None:
        Logger.log("d", "Connection with instance %s with url %s stopped", self._repetier_id, self._base_url)
        self.close()

    def pausePrint(self) -> None:
        self._sendJobCommand("pause")

    def resumePrint(self) -> None:
        if not self._printers[0].activePrintJob:
            return
        #Logger.log("d", "Resume attempted: %s ", self._printers[0].activePrintJob.state)
        if self._printers[0].activePrintJob.state == "paused":
            self._sendJobCommand("start")
        else:
            self._sendJobCommand("pause")

    def cancelPrint(self) -> None:
        self._sendJobCommand("cancel")

    def startPrint(self) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        if self._error_message:
            self._error_message.hide()
            self._error_message = None

        if self._progress_message:
            self._progress_message.hide()
            self._progress_message = None

        self._auto_print = parseBool(global_container_stack.getMetaDataEntry("repetier_auto_print", True))
        self._forced_queue = False

        if self.activePrinter.state not in ["idle", ""]:
            Logger.log("d", "Tried starting a print, but current state is %s" % self.activePrinter.state)
            error_string = ""
            if not self._auto_print:
                # allow queueing the job even if Repetier is currently busy if autoprinting is disabled
                self._error_message = None
            elif self.activePrinter.state == "offline":
                error_string = Message(i18n_catalog.i18nc("@info:status", "The printer is offline. Unable to start a new job."))
            else:
                error_string = Message(i18n_catalog.i18nc("@info:status", "Repetier is busy. Unable to start a new job."))

            if error_string:
                if self._error_message:
                    self._error_message.hide()
                self._error_message = Message(error_string, title=i18n_catalog.i18nc("@label", "Repetier error"))
                self._error_message.addAction(
                    "queue", i18n_catalog.i18nc("@action:button", "Queue job"), "",
                    i18n_catalog.i18nc("@action:tooltip", "Queue this print job so it can be printed later")
                )
                self._error_message.actionTriggered.connect(self._queuePrint)
                self._error_message.show()
                return

        self._startPrint()

    def _stopWaitingForAnalysis(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._waiting_message:
            self._waiting_message.hide()
        self._waiting_for_analysis = False

        for end_point in self._polling_end_points:
            if "files/" in end_point:
                break
        if "files/" not in end_point:
            Logger.log("e", "Could not find files/ endpoint")
            return

        self._polling_end_points = [point for point in self._polling_end_points if not point.startswith("files/")]

        if action_id == "print":
            self._selectAndPrint(end_point)
        elif action_id == "cancel":
            pass

    def _stopWaitingForPrinter(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._waiting_message:
            self._waiting_message.hide()
        self._waiting_for_printer = False

        if action_id == "queue":
            self._queuePrint()
        elif action_id == "cancel":
            self._gcode_stream = StringIO()  # type: Union[StringIO, BytesIO]

    def _queuePrint(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._error_message:
            self._error_message.hide()
        self._forced_queue = True
        self._startPrint()
        
    def _startPrint(self) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        if self._auto_print and not self._forced_queue:
            CuraApplication.getInstance().getController().setActiveStage("MonitorStage")

            # cancel any ongoing preheat timer before starting a print
            try:
                self._printers[0].stopPreheatTimers()
            except AttributeError:
                # stopPreheatTimers was added after Cura 3.3 beta
                pass

        self._progress_message = Message(
            i18n_catalog.i18nc("@info:status", "Sending data to Repetier"),
            title=i18n_catalog.i18nc("@label", "Repetier"),
            progress=-1, lifetime=0, dismissable=False, use_inactivity_timer=False
        )
        self._progress_message.addAction(
            "cancel", i18n_catalog.i18nc("@action:button", "Cancel"), "",
            i18n_catalog.i18nc("@action:tooltip", "Abort the printjob")
        )
        self._progress_message.actionTriggered.connect(self._cancelSendGcode)
        self._progress_message.show()

        job_name = CuraApplication.getInstance().getPrintInformation().jobName.strip()
        Logger.log("d", "Print job: [%s]", job_name)
        if job_name is "":
            job_name = "untitled_print"
        file_name = "%s.gcode" % job_name

        ##  Create multi_part request
        post_parts = [] # type: List[QHttpPart]

            ##  Create parts (to be placed inside multipart)
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"a\"")
        post_part.setBody(b"upload")
        post_parts.append(post_part)

        if self._auto_print and not self._forced_queue:
            post_part = QHttpPart()
            post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"%s\"" % file_name)
            post_part.setBody(b"upload")
            post_parts.append(post_part)
            
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"file\"; filename=\"%s\"" % file_name)
        post_part.setBody(self._gcode_stream.getvalue().encode())
        post_parts.append(post_part)

        destination = "local"
        if self._sd_supported and parseBool(global_container_stack.getMetaDataEntry("Repetier_store_sd", False)):
            destination = "sdcard"

        try:
            #  Post request + data
            #post_request = self._createApiRequest("files/" + destination)
            post_request = self._createEmptyRequest("upload&name=%s" % file_name)
            self._post_reply = self.postFormWithParts("upload&name=%s" % file_name, post_parts, on_finished=self._onUploadFinished, on_progress=self._onUploadProgress)
            #self._post_reply = self._manager.post(post_request, self._post_multi_part)
            #self._post_reply.uploadProgress.connect(self._onUploadProgress)


        except Exception as e:
            self._progress_message.hide()
            self._error_message = Message(
                i18n_catalog.i18nc("@info:status", "Unable to send data to Repetier."),
                title=i18n_catalog.i18nc("@label", "Repetier error")
            )
            self._error_message.show()
            Logger.log("e", "An exception occurred in network connection: %s" % str(e))

        self._gcode_stream = StringIO()

    def _cancelSendGcode(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._post_reply:
            Logger.log("d", "Stopping upload because the user pressed cancel.")
            try:
                self._post_reply.uploadProgress.disconnect(self._onUploadProgress)
            except TypeError:
                pass  # The disconnection can fail on mac in some cases. Ignore that.

            self._post_reply.abort()
            self._post_reply = None
        if self._progress_message:
            self._progress_message.hide()

    def sendCommand(self, command: str) -> None:
        self._queued_gcode_commands.append(command)
        CuraApplication.getInstance().callLater(self._sendQueuedGcode)

    # Send gcode commands that are queued in quick succession as a single batch
    def _sendQueuedGcode(self) -> None:
        if self._queued_gcode_commands:
            for gcode in self._queued_gcode_commands:
                self._sendCommandToApi("send", "&data={\"cmd\":\"" + gcode + "\"}")
                Logger.log("d", "Sent gcode command to Repetier instance: %s", gcode)
            self._queued_gcode_commands = []

    def _sendJobCommand(self, command: str) -> None:
        #Logger.log("d", "sendJobCommand: %s", command)
        if (command=="pause"):
            self._sendCommandToApi("send", "&data={\"cmd\":\"@pause\"}")
        if (command=="start"):
            self._manager.get(self._createEmptyRequest("continueJob"))
        if (command=="cancel"):
            self._manager.get(self._createEmptyRequest("stopJob"))
        #Logger.log("d", "Sent job command to Repetier instance: %s %s" % (command,self.jobState))

    def _sendCommandToApi(self, end_point, commands):        
        command_request = QNetworkRequest(QUrl(self._api_url + "?a=" + end_point))
        command_request.setRawHeader(self._user_agent_header, self._user_agent.encode())
        command_request.setRawHeader(self._api_header, self._api_key)
        if self._basic_auth_data:
            command_request.setRawHeader(self._basic_auth_header, self._basic_auth_data)                
        command_request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        if isinstance(commands, list):
            data = json.dumps({"commands": commands})
        else:
            data = commands
        #Logger.log("d", "_sendCommandToAPI: %s", data)
        self._command_reply = self._manager.post(command_request, data.encode())

        #  Handler for all requests that have finished.
    def _onRequestFinished(self, reply: QNetworkReply) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return
        if reply.error() == QNetworkReply.TimeoutError:
            Logger.log("w", "Received a timeout on a request to the instance")
            self._connection_state_before_timeout = self._connection_state
            self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Error))
            self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier Connection to printer failed"))
            return

        if self._connection_state_before_timeout and reply.error() == QNetworkReply.NoError:
            #  There was a timeout, but we got a correct answer again.
            if self._last_response_time:
                Logger.log("d", "We got a response from the instance after %s of silence", time() - self._last_response_time)
            self.setConnectionState(self._connection_state_before_timeout)
            self._connection_state_before_timeout = None

        if reply.error() == QNetworkReply.NoError:
            self._last_response_time = time()

        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if not http_status_code:
            self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier Connection recevied no data"))
            return

        error_handled = False
        if reply.operation() == QNetworkAccessManager.GetOperation:
            Logger.log("d", "reply.url() = %s", reply.url().toString())
            if self._api_prefix + "?a=stateList" in reply.url().toString():  # Status update from /printer.
                if not self._printers:
                    self._createPrinterList()
                printer = self._printers[0]
                if http_status_code == 200:
                    if not self.acceptsCommands:
                        self._setAcceptsCommands(True)
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to Repetier on {0}").format(self._repetier_id))

                    if self._connection_state == UnifiedConnectionState.Connecting:
                        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connected))
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.1")
                        json_data = {}
                    #if "temperature" in json_data:
                    try:                        
                        if self._repetier_id in json_data:
                            Logger.log("d", "stateList JSON: %s",json_data[self._repetier_id])
                            if "numExtruder" in json_data[self._repetier_id]:
                                self._number_of_extruders = 0
                                printer_state = "idle"
                                #while "tool%d" % self._num_extruders in json_data["temperature"]:
                                self._number_of_extruders=json_data[self._repetier_id]["numExtruder"]
                                if self._number_of_extruders > 1:
                                    # Recreate list of printers to match the new _number_of_extruders
                                     self._createPrinterList()
                                     printer = self._printers[0]

                                if self._number_of_extruders > 0:
                                    self._number_of_extruders_set = True
          
                                # Check for hotend temperatures
                                for index in range(0, self._number_of_extruders):
                                    extruder = printer.extruders[index]
                                    if "extruder" in json_data[self._repetier_id]:                            
                                        hotend_temperatures = json_data[self._repetier_id]["extruder"]
                                        #Logger.log("d", "target end temp %s", hotend_temperatures[index]["tempSet"])
                                        #Logger.log("d", "target end temp %s", hotend_temperatures[index]["tempRead"])
                                        extruder.updateTargetHotendTemperature(round(hotend_temperatures[index]["tempSet"],2))
                                        extruder.updateHotendTemperature(round(hotend_temperatures[index]["tempRead"],2))
                                    else:
                                        extruder.updateTargetHotendTemperature(0)
                                        extruder.updateHotendTemperature(0)
                            #Logger.log("d", "json_data %s", json_data[self._key])
                            if "heatedBed" in json_data[self._repetier_id]:
                                bed_temperatures = json_data[self._repetier_id]["heatedBed"]
                                actual_temperature = bed_temperatures["tempRead"] if bed_temperatures["tempRead"] is not None else -1
                                printer.updateBedTemperature(round(actual_temperature,2))
                                target_temperature = bed_temperatures["tempSet"] if bed_temperatures["tempSet"] is not None else -1                                    
                                printer.updateTargetBedTemperature(round(target_temperature,2))
                                #Logger.log("d", "target bed temp %s", target_temperature)
                                #Logger.log("d", "actual bed temp %s", actual_temperature)
                            else:
                                if "heatedBeds" in json_data[self._repetier_id]:
                                    bed_temperatures = json_data[self._repetier_id]["heatedBeds"][0]
                                    actual_temperature = bed_temperatures["tempRead"] if bed_temperatures["tempRead"] is not None else -1
                                    printer.updateBedTemperature(round(actual_temperature,2))
                                    target_temperature = bed_temperatures["tempSet"] if bed_temperatures["tempSet"] is not None else -1                                    
                                    printer.updateTargetBedTemperature(round(target_temperature,2))
                                    #Logger.log("d", "target bed temp %s", target_temperature)
                                    #Logger.log("d", "actual bed temp %s", actual_temperature)
                                else:
                                    printer.updateBedTemperature(-1)
                                    printer.updateTargetBedTemperature(0)
                                    printer.updateState(printer_state)
                    except:
                        Logger.log("w", "Received invalid JSON from Repetier instance.2")                    
                        json_data = {}
                        printer.activePrintJob.updateState("offline")
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} configuration is invalid").format(self._repetier_id))

                elif http_status_code == 401:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} does not allow access to print").format(self._repetier_id))
                    error_handled = True
                elif http_status_code == 409:
                    if self._connection_state == ConnectionState.Connecting:
                        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connected))
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "The printer connected to Repetier on {0} is not operational").format(self._repetier_id))
                    error_handled = True
                else:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    Logger.log("w", "Received an unexpected returncode: %d", http_status_code)

            elif self._api_prefix + "?a=listPrinter" in reply.url().toString():  # Status update from /job:
                if not self._printers:
                    return
                    #self._createPrinterList()

                printer = self._printers[0]

                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}

                    try:
                        if self._printerindex(json_data,self._repetier_id)>-1:
                            Logger.log("d", "listPrinter JSON: %s",json_data[self._printerindex(json_data,self._repetier_id)])
                            print_job_state = "idle"
                            printer.updateState("idle")
                            Logger.log("d","JSON Dump: %s",json_data[self._printerindex(json_data,self._repetier_id)])
                            if printer.activePrintJob is None:
                                print_job = PrintJobOutputModel(output_controller=self._output_controller)
                                printer.updateActivePrintJob(print_job)
                            else:
                                print_job = printer.activePrintJob
                            if "job" in json_data[self._printerindex(json_data,self._repetier_id)]:                                    
                                if json_data[self._printerindex(json_data,self._repetier_id)]["job"] != "none":
                                    print_job.updateName(json_data[self._printerindex(json_data,self._repetier_id)]["job"])
                                    print_job_state = "printing"
                                if json_data[self._printerindex(json_data,self._repetier_id)]["job"] == "none":                                
                                    print_job_state = "idle"
                                    printer.updateState("idle")
                                    print_job = PrintJobOutputModel(output_controller=self._output_controller)
                                    printer.updateActivePrintJob(print_job)
                            if "paused" in json_data[self._printerindex(json_data,self._repetier_id)]:
                                if json_data[self._printerindex(json_data,self._repetier_id)]["paused"] != False:
                                    print_job_state = "paused"                                                                
                            print_job.updateState(print_job_state)                                
                            if "done" in json_data[self._printerindex(json_data,self._repetier_id)]:
                                progress = json_data[self._printerindex(json_data,self._repetier_id)]["done"]
                            if "start" in json_data[self._printerindex(json_data,self._repetier_id)]:
                                if json_data[self._printerindex(json_data,self._repetier_id)]["start"]:
                                    if json_data[self._printerindex(json_data,self._repetier_id)]["printTime"]:
                                        print_job.updateTimeTotal(json_data[self._printerindex(json_data,self._repetier_id)]["printTime"])
                                    if json_data[self._printerindex(json_data,self._repetier_id)]["printedTimeComp"]:
                                        print_job.updateTimeElapsed(json_data[self._printerindex(json_data,self._repetier_id)]["printedTimeComp"])
                                    elif progress > 0:
                                        print_job.updateTimeTotal(json_data[self._printerindex(json_data,self._repetier_id)]["printTime"] * (progress / 100))
                                    else:
                                        print_job.updateTimeTotal(0)
                                else:
                                    print_job.updateTimeElapsed(0)
                                    print_job.updateTimeTotal(0)
                                print_job.updateName(json_data[self._printerindex(json_data,self._repetier_id)]["job"])
                    except:
                        printer.activePrintJob.updateState("offline")
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} configuration is invalid").format(self._key))
                else:
                    printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} bad response").format(self._repetier_id))
            elif self._api_prefix + "?a=getPrinterConfig" in reply.url().toString():  # Repetier settings dump from /settings:                
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}

                    if "general" in json_data and "sdcard" in json_data["general"]:
                        self._sd_supported = json_data["general"]["sdcard"]

                    if "webcam" in json_data and "dynamicUrl" in json_data["webcam"]:
                        Logger.log("d", "RepetierOutputDevice: Detected Repetier 89.X")
                        self._camera_shares_proxy = False
                        Logger.log("d", "RepetierOutputDevice: Checking streamurl")                        
                        stream_url = json_data["webcam"]["dynamicUrl"].replace("127.0.0.1",self._address)
                        if not stream_url: #empty string or None
                            self._camera_url = ""
                        elif stream_url[:4].lower() == "http": # absolute uri                        Logger.log("d", "RepetierOutputDevice: stream_url: %s",stream_url)
                            self._camera_url=stream_url
                        elif stream_url[:2] == "//": # protocol-relative
                            self._camera_url = "%s:%s" % (self._protocol, stream_url)
                        elif stream_url[:1] == ":": # domain-relative (on another port)
                            self._camera_url = "%s://%s%s" % (self._protocol, self._address, stream_url)
                        elif stream_url[:1] == "/": # domain-relative (on same port)
                            self._camera_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, stream_url)
                            self._camera_shares_proxy = True
                        else:
                            Logger.log("w", "Unusable stream url received: %s", stream_url)
                            self._camera_url = ""
                        if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamflip_y", False)):
                            self._camera_mirror = True
                        else:
                            self._camera_mirror = False
                        if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamflip_x", False)):
                            self._camera_rotation = 180
                            self._camera_mirror = True
                        if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_90", False)):
                            self._camera_rotation = 90
                        if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_180", False)):
                            self._camera_rotation = 180
                        if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_270", False)):
                            self._camera_rotation = 270
                        Logger.log("d", "Set Repetier camera url to %s", self._camera_url)
                        self.cameraUrlChanged.emit()
                        self._camera_mirror = False
                        #self.cameraOrientationChanged.emit()
                    if "webcams" in json_data:
                        Logger.log("d", "RepetierOutputDevice: Detected Repetier 90.X")
                        if len(json_data["webcams"])>0:
                            if "dynamicUrl" in json_data["webcams"][0]:
                                self._camera_shares_proxy = False
                                Logger.log("d", "RepetierOutputDevice: Checking streamurl")                        
                                stream_url = json_data["webcams"][0]["dynamicUrl"].replace("127.0.0.1",self._address)
                                if not stream_url: #empty string or None
                                    self._camera_url = ""
                                elif stream_url[:4].lower() == "http": # absolute uri                        Logger.log("d", "RepetierOutputDevice: stream_url: %s",stream_url)
                                    self._camera_url=stream_url
                                elif stream_url[:2] == "//": # protocol-relative
                                    self._camera_url = "%s:%s" % (self._protocol, stream_url)
                                elif stream_url[:1] == ":": # domain-relative (on another port)
                                    self._camera_url = "%s://%s%s" % (self._protocol, self._address, stream_url)
                                elif stream_url[:1] == "/": # domain-relative (on same port)
                                    self._camera_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, stream_url)
                                    self._camera_shares_proxy = True
                                else:
                                    Logger.log("w", "Unusable stream url received: %s", stream_url)
                                    self._camera_url = ""
                                Logger.log("d", "Set Repetier camera url to %s", self._camera_url)
                                if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamflip_y", False)):
                                    self._camera_mirror = True
                                else:
                                    self._camera_mirror = False
                                if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamflip_x", False)):
                                    self._camera_rotation = 180
                                    self._camera_mirror = True
                                if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_90", False)):
                                    self._camera_rotation = 90
                                if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_180", False)):
                                    self._camera_rotation = 180
                                if parseBool(global_container_stack.getMetaDataEntry("repetier_webcamrot_270", False)):
                                    self._camera_rotation = 270                                
                                self.cameraUrlChanged.emit()
        elif reply.operation() == QNetworkAccessManager.PostOperation:
            if self._api_prefix + "?a=listModels" in reply.url().toString():  # Result from /files command:
                if http_status_code == 201:
                    Logger.log("d", "Resource created on Repetier instance: %s", reply.header(QNetworkRequest.LocationHeader).toString())
                else:
                    pass  # TODO: Handle errors

                reply.uploadProgress.disconnect(self._onUploadProgress)
                if self._progress_message:
                    self._progress_message.hide()
                global_container_stack = Application.getInstance().getGlobalContainerStack()
                if self._forced_queue or not self._auto_print:
                    location = reply.header(QNetworkRequest.LocationHeader)
                    if location:
                        file_name = QUrl(reply.header(QNetworkRequest.LocationHeader).toString()).fileName()
                        message = Message(i18n_catalog.i18nc("@info:status", "Saved to Repetier as {0}").format(file_name))
                    else:
                        message = Message(i18n_catalog.i18nc("@info:status", "Saved to Repetier"))
                    message.addAction("open_browser", i18n_catalog.i18nc("@action:button", "Open Repetier..."), "globe",
                                        i18n_catalog.i18nc("@info:tooltip", "Open the Repetier web interface"))
                    message.actionTriggered.connect(self._openRepetierPrint)
                    message.show()

            elif self._api_prefix + "?a=send" in reply.url().toString():  # Result from /job command:
                if http_status_code == 204:
                    Logger.log("d", "Repetier command accepted")
                else:
                    pass  # TODO: Handle errors


        else:
            Logger.log("d", "RepetierOutputDevice got an unhandled operation %s", reply.operation())

        if not error_handled and http_status_code >= 400:
            # Received an error reply
            error_string = bytes(reply.readAll()).decode("utf-8")
            if not error_string:
                error_string = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            if self._error_message:
                self._error_message.hide()
            #self._error_message = Message(i18n_catalog.i18nc("@info:status", "Repetier returned an error: {0}.").format(error_string))
            self._error_message = Message(error_string, title=i18n_catalog.i18nc("@label", "Repetier error"))
            self._error_message.show()
            return
    def _onUploadProgress(self, bytes_sent: int, bytes_total: int) -> None:
        if not self._progress_message:
            return

        if bytes_total > 0:
            # Treat upload progress as response. Uploading can take more than 10 seconds, so if we don't, we can get
            # timeout responses if this happens.
            self._last_response_time = time()

            progress = bytes_sent / bytes_total * 100
            previous_progress = self._progress_message.getProgress()
            if progress < 100:
                if previous_progress is not None and progress > previous_progress:
                    self._progress_message.setProgress(progress)
            else:
                self._progress_message.hide()
                self._progress_message = Message(
                    i18n_catalog.i18nc("@info:status", "Storing data on Repetier"), 0, False, -1, title=i18n_catalog.i18nc("@label", "Repetier")
                )
                self._progress_message.show()
        else:
            self._progress_message.setProgress(0)

    def _printerindex(self, jsonstr:str, repetier_id:str) -> int:
        count = 0
        rv=-1
        for i in jsonstr:
            if "slug" in i:
                if i["slug"]==repetier_id:
                    return count
            count=count+1
        return rv        
    def _onUploadFinished(self, reply: QNetworkReply) -> None:
        reply.uploadProgress.disconnect(self._onUploadProgress)

        Logger.log("d", "_onUploadFinished %s", reply.url().toString())
        if self._progress_message:
            self._progress_message.hide()

        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        Logger.log("d", "_onUploadFinished http_status_code=%d", http_status_code)		
        error_string = ""
        if http_status_code == 401:
            error_string = i18n_catalog.i18nc("@info:error", "You are not allowed to upload files to Repetier with the configured API key.")

        elif http_status_code == 409:
            if "files/sdcard/" in reply.url().toString():
                error_string = i18n_catalog.i18nc("@info:error", "Can't store the printjob on the printer sd card.")
            else:
                error_string = i18n_catalog.i18nc("@info:error", "Can't store the printjob with the same name as the one that is currently printing.")

        elif ((http_status_code != 201) and (http_status_code != 200)):
            error_string = bytes(reply.readAll()).decode("utf-8")
            if not error_string:
                error_string = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)

        if error_string:
            self._showErrorMessage(error_string)
            Logger.log("e", "RepetierOutputDevice got an error uploading %s", reply.url().toString())
            Logger.log("e", error_string)
            return

        location_url = reply.header(QNetworkRequest.LocationHeader)
        Logger.log("d", "Resource created on Repetier instance: %s", location_url.toString())

        if self._forced_queue or not self._auto_print:
            if location_url:
                file_name = location_url.fileName()
                message = Message(i18n_catalog.i18nc("@info:status", "Saved to Repetier as {0}").format(file_name))
            else:
                message = Message(i18n_catalog.i18nc("@info:status", "Saved to Repetier"))
            message.setTitle(i18n_catalog.i18nc("@label", "Repetier"))
            message.addAction(
                "open_browser", i18n_catalog.i18nc("@action:button", "Repetier..."), "globe",
                i18n_catalog.i18nc("@info:tooltip", "Open the Repetier web interface")
            )
            message.actionTriggered.connect(self._openRepetier)
            message.show()
        elif self._auto_print:
            end_point = location_url.toString().split(self._api_prefix, 1)[1]
            if self._ufp_supported and end_point.endswith(".ufp"):
                end_point += ".gcode"

            if not self._wait_for_analysis:
                self._selectAndPrint(end_point)
                return

            self._waiting_message = Message(
                i18n_catalog.i18nc("@info:status", "Waiting for Repetier to complete Gcode analysis..."),
                title=i18n_catalog.i18nc("@label", "Repetier"),
                progress=-1, lifetime=0, dismissable=False, use_inactivity_timer=False
            )
            self._waiting_message.addAction(
                "print", i18n_catalog.i18nc("@action:button", "Print now"), "",
                i18n_catalog.i18nc("@action:tooltip", "Stop waiting for the Gcode analysis and start printing immediately"),
                button_style=Message.ActionButtonStyle.SECONDARY
            )
            self._waiting_message.addAction(
                "cancel", i18n_catalog.i18nc("@action:button", "Cancel"), "",
                i18n_catalog.i18nc("@action:tooltip", "Abort the printjob")
            )
            self._waiting_message.actionTriggered.connect(self._stopWaitingForAnalysis)
            self._waiting_message.show()

            self._waiting_for_analysis = True
            self._polling_end_points.append(end_point)  # start polling the API for information about this file

    def _createPrinterList(self) -> None:
        printer = PrinterOutputModel(output_controller=self._output_controller, number_of_extruders=self._number_of_extruders)
        printer.updateName(self.name)
        self._printers = [printer]
        self.printersChanged.emit()

    def _selectAndPrint(self, end_point: str) -> None:
        command = {
            "command": "select",
            "print": True
        }
        self._sendCommandToApi(end_point, command)

    def _showErrorMessage(self, error_string: str) -> None:
        if self._error_message:
            self._error_message.hide()
        self._error_message = Message(error_string, title=i18n_catalog.i18nc("@label", "Repetier error"))
        self._error_message.show()

    def _openRepetierPrint(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        QDesktopServices.openUrl(QUrl(self._base_url))

    def _createEmptyRequest(self, target: str, content_type: Optional[str] = "application/json") -> QNetworkRequest:
        if "upload" in target:
             if self._forced_queue or not self._auto_print:
                  request = QNetworkRequest(QUrl(self._save_url + "?a=" + target))
             else:
                  request = QNetworkRequest(QUrl(self._job_url + "?a=" + target))
        else:	
             request = QNetworkRequest(QUrl(self._api_url + "?a=" + target))
        request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)

        request.setRawHeader(b"X-Api-Key", self._api_key)
        request.setRawHeader(b"User-Agent", self._user_agent.encode())

        if content_type is not None:
            request.setHeader(QNetworkRequest.ContentTypeHeader, content_type)

        # ignore SSL errors (eg for self-signed certificates)
        ssl_configuration = QSslConfiguration.defaultConfiguration()
        ssl_configuration.setPeerVerifyMode(QSslSocket.VerifyNone)
        request.setSslConfiguration(ssl_configuration)

        if self._basic_auth_data:
            request.setRawHeader(b"Authorization", self._basic_auth_data)

        return request

    # This is a patched version from NetworkedPrinterOutputdevice, which adds "form_data" instead of "form-data"
    def _createFormPart(self, content_header: str, data: bytes, content_type: Optional[str] = None) -> QHttpPart:
        part = QHttpPart()

        if not content_header.startswith("form-data;"):
            content_header = "form-data; " + content_header
        part.setHeader(QNetworkRequest.ContentDispositionHeader, content_header)
        if content_type is not None:
            part.setHeader(QNetworkRequest.ContentTypeHeader, content_type)

        part.setBody(data)
        return part

    ## Overloaded from NetworkedPrinterOutputDevice.get() to be permissive of
    #  self-signed certificates
    def get(self, url: str, on_finished: Optional[Callable[[QNetworkReply], None]]) -> None:
        Logger.log("d", "get request: %s", url)
        self._validateManager()

        request = self._createEmptyRequest(url)
        self._last_request_time = time()

        if not self._manager:
            Logger.log("e", "No network manager was created to execute the GET call with.")
            return

        reply = self._manager.get(request)
        self._registerOnFinishedCallback(reply, on_finished)

    ## Overloaded from NetworkedPrinterOutputDevice.post() to backport https://github.com/Ultimaker/Cura/pull/4678
    #  and allow self-signed certificates
    def post(self, url: str, data: Union[str, bytes],
             on_finished: Optional[Callable[[QNetworkReply], None]],
             on_progress: Optional[Callable[[int, int], None]] = None) -> None:
        self._validateManager()

        request = self._createEmptyRequest(url)
        self._last_request_time = time()

        if not self._manager:
            Logger.log("e", "Could not find manager.")
            return

        body = data if isinstance(data, bytes) else data.encode()  # type: bytes
        reply = self._manager.post(request, body)
        if on_progress is not None:
            reply.uploadProgress.connect(on_progress)
        self._registerOnFinishedCallback(reply, on_finished)