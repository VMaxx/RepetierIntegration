from UM.i18n import i18nCatalog
from UM.Application import Application
from UM.Logger import Logger
from UM.Signal import signalemitter
from UM.Message import Message
from UM.Util import parseBool

from cura.PrinterOutputDevice import PrinterOutputDevice, ConnectionState
from cura.PrinterOutput.NetworkedPrinterOutputDevice import NetworkedPrinterOutputDevice
from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel
from cura.PrinterOutput.PrintJobOutputModel import PrintJobOutputModel
from cura.PrinterOutput.NetworkCamera import NetworkCamera

from cura.PrinterOutput.GenericOutputController import GenericOutputController

from PyQt5.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkRequest, QNetworkAccessManager, QNetworkReply
from PyQt5.QtCore import QUrl, QTimer, pyqtSignal, pyqtProperty, pyqtSlot, QCoreApplication
from PyQt5.QtGui import QImage, QDesktopServices

import json
import os.path
import datetime
from time import time
import base64

i18n_catalog = i18nCatalog("cura")


##  Repetier connected (wifi / lan) printer using the Repetier API
@signalemitter
class RepetierOutputDevice(NetworkedPrinterOutputDevice):
    def __init__(self, key, address: str, port, properties, parent = None):
        super().__init__(device_id = key, address = address, properties = properties, parent = parent)

        self._address = address
        self._port = port
        self._path = properties.get(b"path", b"/").decode("utf-8")
        if self._path[-1:] != "/":
            self._path += "/"
        self._key = key        
        self._properties = properties  # Properties dict as provided by zero conf

        self._gcode = None
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
            Application.getInstance().getApplicationName(),
            Application.getInstance().getVersion(),
            "RepetierPlugin",
            Application.getInstance().getVersion()
        )).encode()

        #base_url + "printer/api/" + self._key +
        self._api_prefix = "printer/api/" + self._key 
        self._job_prefix = "printer/job/" + self._key 
        self._api_header = "x-api-key".encode()
        self._api_key = None

        self._protocol = "https" if properties.get(b'useHttps') == b"true" else "http"
        self._base_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, self._path)
        self._api_url = self._base_url + self._api_prefix
        self._job_url = self._base_url + self._job_prefix

        self._basic_auth_header = "Authorization".encode()
        self._basic_auth_data = None
        basic_auth_username = properties.get(b"userName", b"").decode("utf-8")
        basic_auth_password = properties.get(b"password", b"").decode("utf-8")
        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(("%s:%s" % (basic_auth_username, basic_auth_password)).encode()).decode("utf-8")
            self._basic_auth_data = ("basic %s" % data).encode()

        self._monitor_view_qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MonitorItem.qml")

        self.setPriority(2) # Make sure the output device gets selected above local file output
        self.setName(key)
        self.setShortDescription(i18n_catalog.i18nc("@action:button", "Print with Repetier"))
        self.setDescription(i18n_catalog.i18nc("@properties:tooltip", "Print with Repetier"))
        self.setIconName("print")
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to Repetier on {0}").format(self._key))

        #   QNetwork manager needs to be created in advance. If we don't it can happen that it doesn't correctly
        #   hook itself into the event loop, which results in events never being fired / done.
        self._manager = QNetworkAccessManager()
        self._manager.finished.connect(self._onRequestFinished)

        ##  Ensure that the qt networking stuff isn't garbage collected (unless we want it to)
        self._settings_reply = None
        self._printer_reply = None
        self._job_reply = None
        self._command_reply = None

        self._post_reply = None
        self._post_multi_part = None

        self._progress_message = None
        self._error_message = None
        self._connection_message = None

        self._queued_gcode_commands = []
        self._queued_gcode_timer = QTimer()
        self._queued_gcode_timer.setInterval(0)
        self._queued_gcode_timer.setSingleShot(True)
        self._queued_gcode_timer.timeout.connect(self._sendQueuedGcode)

        self._update_timer = QTimer()
        self._update_timer.setInterval(2000)  # TODO; Add preference for update interval
        self._update_timer.setSingleShot(False)
        self._update_timer.timeout.connect(self._update)

        self._camera_mirror = ""
        self._camera_rotation = 0
        self._camera_url = ""
        self._camera_shares_proxy = False

        self._sd_supported = False

        self._connection_state_before_timeout = None

        self._last_response_time = None
        self._last_request_time = None
        self._response_timeout_time = 5
        self._recreate_network_manager_time = 30 # If we have no connection, re-create network manager every 30 sec.
        self._recreate_network_manager_count = 1

        self._output_controller = GenericOutputController(self)
        
    def getProperties(self):
        return self._properties

    @pyqtSlot(str, result = str)
    def getProperty(self, key):
        key = key.encode("utf-8")
        if key in self._properties:
            return self._properties.get(key, b"").decode("utf-8")
        else:
            return ""

    ##  Get the unique key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(result = str)
    def getKey(self):
        return self._key

    ##  Set the API key of this Repetier instance
    def setApiKey(self, api_key):        
        self._api_key = api_key.encode()        

    ##  Name of the instance (as returned from the zeroConf properties)
    @pyqtProperty(str, constant = True)
    def name(self):
        return self._key

    ##  Version (as returned from the zeroConf properties)
    @pyqtProperty(str, constant=True)
    def repetierVersion(self):
        return self._properties.get(b"version", b"").decode("utf-8")

    ## IPadress of this instance
    @pyqtProperty(str, constant=True)
    def ipAddress(self):
        return self._address

    ## IP address of this instance
    @pyqtProperty(str, constant=True)
    def address(self):
        return self._address

    ## port of this instance
    @pyqtProperty(int, constant=True)
    def port(self):
        return self._port

    ## path of this instance
    @pyqtProperty(str, constant=True)
    def path(self):
        return self._path

    ## absolute url of this instance
    @pyqtProperty(str, constant=True)
    def baseURL(self):
        return self._base_url

    cameraOrientationChanged = pyqtSignal()

    @pyqtProperty("QVariantMap", notify = cameraOrientationChanged)
    def cameraOrientation(self):
        return {
            "mirror": self._camera_mirror,
            "rotation": self._camera_rotation,
        }

    def _update(self):
        if self._last_response_time:
            time_since_last_response = time() - self._last_response_time
        else:
            time_since_last_response = 0
        if self._last_request_time:
            time_since_last_request = time() - self._last_request_time
        else:
            time_since_last_request = float("inf") # An irrelevantly large number of seconds

        # Connection is in timeout, check if we need to re-start the connection.
        # Sometimes the qNetwork manager incorrectly reports the network status on Mac & Windows.
        # Re-creating the QNetworkManager seems to fix this issue.
        if self._last_response_time and self._connection_state_before_timeout:
            if time_since_last_response > self._recreate_network_manager_time * self._recreate_network_manager_count:
                self._recreate_network_manager_count += 1
                # It can happen that we had a very long timeout (multiple times the recreate time).
                # In that case we should jump through the point that the next update won't be right away.
                while time_since_last_response - self._recreate_network_manager_time * self._recreate_network_manager_count > self._recreate_network_manager_time:
                    self._recreate_network_manager_count += 1
                Logger.log("d", "Timeout lasted over 30 seconds (%.1fs), re-checking connection.", time_since_last_response)
                self._createNetworkManager()
                return

        # Check if we have an connection in the first place.
        if not self._manager.networkAccessible():
            if not self._connection_state_before_timeout:
                Logger.log("d", "The network connection seems to be disabled. Going into timeout mode")
                self._connection_state_before_timeout = self._connection_state
                self.setConnectionState(ConnectionState.error)
                self._connection_message = Message(i18n_catalog.i18nc("@info:status",
                                                                      "The connection with the network was lost."))
                self._connection_message.show()
                # Check if we were uploading something. Abort if this is the case.
                # Some operating systems handle this themselves, others give weird issues.
                try:
                    if self._post_reply:
                        Logger.log("d", "Stopping post upload because the connection was lost.")
                        try:
                            self._post_reply.uploadProgress.disconnect(self._onUploadProgress)
                        except TypeError:
                            pass  # The disconnection can fail on mac in some cases. Ignore that.

                        self._post_reply.abort()
                        self._progress_message.hide()
                except RuntimeError:
                    self._post_reply = None  # It can happen that the wrapped c++ object is already deleted.
            return
        else:
            if not self._connection_state_before_timeout:
                self._recreate_network_manager_count = 1

        # Check that we aren't in a timeout state
        if self._last_response_time and self._last_request_time and not self._connection_state_before_timeout:
            if time_since_last_response > self._response_timeout_time and time_since_last_request <= self._response_timeout_time:
                # Go into timeout state.
                Logger.log("d", "We did not receive a response for %s seconds, so it seems Repetier is no longer accesible.", time() - self._last_response_time)
                self._connection_state_before_timeout = self._connection_state
                self._connection_message = Message(i18n_catalog.i18nc("@info:status", "The connection with Repetier was lost. Check your network-connections."))
                self._connection_message.show()
                self.setConnectionState(ConnectionState.error)

        ## Request 'general' printer data
        self._printer_reply = self._manager.get(self._createApiRequest("stateList"))

        ## Request print_job data
        self._job_reply = self._manager.get(self._createApiRequest("listPrinter"))

    def _createNetworkManager(self):
        if self._manager:
            self._manager.finished.disconnect(self._onRequestFinished)

        self._manager = QNetworkAccessManager()
        self._manager.finished.connect(self._onRequestFinished)

    def _createApiRequest(self, end_point):
        #Logger.log("d", "_createApiRequest Debug: %s", end_point)
        if "upload" in end_point:
            request = QNetworkRequest(QUrl(self._job_url + "?a=" + end_point))
        else:
            request = QNetworkRequest(QUrl(self._api_url + "?a=" + end_point))
        request.setRawHeader(self._user_agent_header, self._user_agent)
        request.setRawHeader(self._api_header, self._api_key)
        if self._basic_auth_data:
            request.setRawHeader(self._basic_auth_header, self._basic_auth_data)
        return request

    def close(self):
        self.setConnectionState(ConnectionState.closed)
        if self._progress_message:
            self._progress_message.hide()
        if self._error_message:
            self._error_message.hide()
        self._update_timer.stop()

    def requestWrite(self, node, file_name = None, filter_by_machine = False, file_handler = None, **kwargs):
        self.writeStarted.emit(self)

        active_build_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate
        scene = Application.getInstance().getController().getScene()
        gcode_dict = getattr(scene, "gcode_dict", None)
        if not gcode_dict:
            return
        self._gcode = gcode_dict.get(active_build_plate, None)

        self.startPrint()

    ##  Start requesting data from the instance
    def connect(self):
        self._createNetworkManager()

        self.setConnectionState(ConnectionState.connecting)
        self._update()  # Manually trigger the first update, as we don't want to wait a few secs before it starts.
        Logger.log("d", "Connection with instance %s with url %s started", self._key, self._base_url)
        self._update_timer.start()

        self._last_response_time = None
        self._setAcceptsCommands(False)
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connecting to Repetier on {0}").format(self._base_url))

        ## Request 'settings' dump
        self._settings_reply = self._manager.get(self._createApiRequest("getPrinterConfig"))
        self._settings_reply = self._manager.get(self._createApiRequest("stateList"))

    ##  Stop requesting data from the instance
    def disconnect(self):
        Logger.log("d", "Connection with instance %s with url %s stopped", self._key, self._base_url)
        self.close()

    def pausePrint(self):
        self._sendJobCommand("pause")


    def resumePrint(self):
        if not self._printers[0].activePrintJob:
            return

        if self._printers[0].activePrintJob.state == "paused":
            self._sendJobCommand("pause")
        else:
            self._sendJobCommand("start")

    def cancelPrint(self):
        self._sendJobCommand("cancel")

    def startPrint(self):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
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
            if self.activePrinter.state == "offline":
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "Repetier is offline. Unable to start a new job."))
            elif self._auto_print:
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "Repetier is busy. Unable to start a new job."))
            else:
                # allow queueing the job even if Repetier is currently busy if autoprinting is disabled
                self._error_message = None

            if self._error_message:
                self._error_message.addAction("Queue", i18n_catalog.i18nc("@action:button", "Queue job"), None, i18n_catalog.i18nc("@action:tooltip", "Queue this print job so it can be printed later"))
                self._error_message.actionTriggered.connect(self._queuePrint)
                self._error_message.show()
                return

        self._startPrint()

    def _queuePrint(self, message_id, action_id):
        if self._error_message:
            self._error_message.hide()
        self._forced_queue = True
        self._startPrint()
        
    def _startPrint(self):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if self._auto_print and not self._forced_queue:
            Application.getInstance().getController().setActiveStage("MonitorStage")

            # cancel any ongoing preheat timer before starting a print
            try:
                self._printers[0].stopPreheatTimers()
            except AttributeError:
                # stopPreheatTimers was added after Cura 3.3 beta
                pass

        self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Sending data to Repetier"), 0, False, -1)
        self._progress_message.addAction("Cancel", i18n_catalog.i18nc("@action:button", "Cancel"), None, "")
        self._progress_message.actionTriggered.connect(self._cancelSendGcode)
        self._progress_message.show()

        ## Mash the data into single string
        single_string_file_data = ""
        last_process_events = time()
        for line in self._gcode:
            single_string_file_data += line
            if time() > last_process_events + 0.05:
                # Ensure that the GUI keeps updated at least 20 times per second.
                QCoreApplication.processEvents()
                last_process_events = time()

        job_name = Application.getInstance().getPrintInformation().jobName.strip()
        #Logger.log("d", "debug Print job: [%s]", job_name)
        if job_name is "":
            job_name = "untitled_print"
        file_name = "%s.gcode" % job_name

        ##  Create multi_part request
        self._post_multi_part = QHttpMultiPart(QHttpMultiPart.FormDataType)

            ##  Create parts (to be placed inside multipart)
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"a\"")
        post_part.setBody(b"upload")
        self._post_multi_part.append(post_part)

        ##if self._auto_print and not self._forced_queue:
        ##    post_part = QHttpPart()
        ##    post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"print\"")
        ##    post_part.setBody(b"upload")
        ##    self._post_multi_part.append(post_part)
            
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"file\"; filename=\"%s\"" % file_name)
        post_part.setBody(single_string_file_data.encode())
        self._post_multi_part.append(post_part)
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"name\"")
        b = bytes(file_name, 'utf-8')
        post_part.setBody(b)
        self._post_multi_part.append(post_part)

        destination = "local"
        if self._sd_supported and parseBool(global_container_stack.getMetaDataEntry("Repetier_store_sd", False)):
            destination = "sdcard"

        try:
            ##  Post request + data
            #post_request = self._createApiRequest("files/" + destination)
            post_request = self._createApiRequest("upload")
            self._post_reply = self._manager.post(post_request, self._post_multi_part)
            self._post_reply.uploadProgress.connect(self._onUploadProgress)

        except IOError:
            self._progress_message.hide()
            self._error_message = Message(i18n_catalog.i18nc("@info:status", "Unable to send data to Repetier."))
            self._error_message.show()
        except Exception as e:
            self._progress_message.hide()
            Logger.log("e", "An exception occurred in network connection: %s" % str(e))

        self._gcode = None

    def _cancelSendGcode(self, message_id, action_id):
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

    def sendCommand(self, command):
        self._queued_gcode_commands.append(command)
        self._queued_gcode_timer.start()

    # Send gcode commands that are queued in quick succession as a single batch
    def _sendQueuedGcode(self):
        if self._queued_gcode_commands:
            #self._sendCommandToApi("printer/command", self._queued_gcode_commands)
            self._sendCommandToApi("send", "&data={\"cmd\":\"" + self._queued_gcode_commands + "\"}")
            Logger.log("d", "Sent gcode command to Repetier instance: %s", self._queued_gcode_commands)
            self._queued_gcode_commands = []

    def _sendJobCommand(self, command):
        #self._sendCommandToApi("job", command)
        if (command=="pause"):
            if (self.jobState=="paused"):
                self._manager.get(self._createApiRequest("continueJob"))                
                ##self._sendCommandToApi("send", "&data={\"cmd\":\"continueJob\"}")                
            else:
                self._sendCommandToApi("send", "&data={\"cmd\":\"@pause\"}")
        if (command=="cancel"):            
            self._manager.get(self._createApiRequest("stopJob"))            
            ##self._sendCommandToApi("send", "&data={\"cmd\":\"stopJob\"}")
        #Logger.log("d", "Sent job command to Repetier instance: %s %s" % (command,self.jobState))

    def _sendCommandToApi(self, end_point, commands):
        command_request = self._createApiRequest(end_point)
        command_request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        if isinstance(commands, list):
            data = json.dumps({"commands": commands})
        else:
            data = json.dumps({"command": commands})            
            #data = "{\"command\": \"%s\"}" % commands

        self._command_reply = self._manager.post(command_request, data.encode())


        ##  Handler for all requests that have finished.
    def _onRequestFinished(self, reply):
        if reply.error() == QNetworkReply.TimeoutError:
            Logger.log("w", "Received a timeout on a request to the instance")
            self._connection_state_before_timeout = self._connection_state
            self.setConnectionState(ConnectionState.error)
            return

        if self._connection_state_before_timeout and reply.error() == QNetworkReply.NoError:  #  There was a timeout, but we got a correct answer again.
            if self._last_response_time:
                Logger.log("d", "We got a response from the instance after %s of silence", time() - self._last_response_time)
            self.setConnectionState(self._connection_state_before_timeout)
            self._connection_state_before_timeout = None

        if reply.error() == QNetworkReply.NoError:
            self._last_response_time = time()

        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if not http_status_code:
            # Received no or empty reply
            return

        if reply.operation() == QNetworkAccessManager.GetOperation:
            if self._api_prefix + "?a=stateList" in reply.url().toString():  # Status update from /printer.
                if not self._printers:
                    self._createPrinterList()

                printer = self._printers[0]

                if http_status_code == 200:
                    if not self.acceptsCommands:
                        self._setAcceptsCommands(True)
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to Repetier on {0}").format(self._key))

                    if self._connection_state == ConnectionState.connecting:
                        self.setConnectionState(ConnectionState.connected)
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}
                    #if "temperature" in json_data:
                    try:
                        if "numExtruder" in json_data[self._key]:
                            self._number_of_extruders = 0
                            printer_state = "idle"
                            #while "tool%d" % self._num_extruders in json_data["temperature"]:
                            self._number_of_extruders=json_data[self._key]["numExtruder"]
                            if self._number_of_extruders > 1:
                                # Recreate list of printers to match the new _number_of_extruders
                                self._createPrinterList()
                                printer = self._printers[0]

                            if self._number_of_extruders > 0:
                                self._number_of_extruders_set = True
      
                            # Check for hotend temperatures
                            for index in range(0, self._number_of_extruders):
                                extruder = printer.extruders[index]
                                if "extruder" in json_data[self._key]:                            
                                    hotend_temperatures = json_data[self._key]["extruder"]
                                    #Logger.log("d", "target end temp %s", hotend_temperatures[index]["tempSet"])
                                    #Logger.log("d", "target end temp %s", hotend_temperatures[index]["tempRead"])
                                    extruder.updateTargetHotendTemperature(hotend_temperatures[index]["tempSet"])
                                    extruder.updateHotendTemperature(hotend_temperatures[index]["tempRead"])                                    
                                else:
                                    extruder.updateTargetHotendTemperature(0)
                                    extruder.updateHotendTemperature(0)
                        #Logger.log("d", "json_data %s", json_data[self._key])
                        if "heatedBed" in json_data[self._key]:
                            bed_temperatures = json_data[self._key]["heatedBed"]
                            actual_temperature = bed_temperatures["tempRead"] if bed_temperatures["tempRead"] is not None else -1
                            printer.updateBedTemperature(actual_temperature)
                            target_temperature = bed_temperatures["tempSet"] if bed_temperatures["tempSet"] is not None else -1                                    
                            printer.updateTargetBedTemperature(target_temperature)
                            #Logger.log("d", "target bed temp %s", target_temperature)
                            #Logger.log("d", "actual bed temp %s", actual_temperature)
                        else:
                            printer.updateBedTemperature(-1)
                            printer.updateTargetBedTemperature(0)
                        printer.updateState(printer_state)
                    except:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")                    
                        json_data = {}
                        printer.activePrintJob.updateState("offline")
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} configuration is invalid").format(self._key))

                elif http_status_code == 401:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} does not allow access to print").format(self._key))
                    pass
                elif http_status_code == 409:
                    if self._connection_state == ConnectionState.connecting:
                        self.setConnectionState(ConnectionState.connected)

                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "The printer connected to Repetier on {0} is not operational").format(self._key))
                else:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    Logger.log("w", "Received an unexpected returncode: %d", http_status_code)

            elif self._api_prefix + "?a=listPrinter" in reply.url().toString():  # Status update from /job:
                if not self._printers:
                    self._createPrinterList()
                printer = self._printers[0]
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from Repetier instance.")
                        json_data = {}

                    #try:
                    if printer:
                        print_job_state = "ready"
                        printer.updateState("idle")
                        if printer.activePrintJob is None:
                            print_job = PrintJobOutputModel(output_controller=self._output_controller)
                            printer.updateActivePrintJob(print_job)
                        else:
                            print_job = printer.activePrintJob
                            #job_state = "ready"
                            #if "job" in json_data[0]:
                            #    if json_data[0]["job"] != "none":
                            #        job_state = "printing"

                        print_job_state = "ready"
                        if "job" in json_data[0]:
                            Logger.log("d","Jobname: %s",json_data[0]["job"])
                            if json_data[0]["job"] != "none":
                                print_job.updateName(json_data[0]["job"])
                                print_job_state = "printing"
                        if "paused" in json_data[0]:
                            if json_data[0]["paused"] != False:
                                print_job_state = "paused"
                        #printer.updateState(printer_state)
                        #if "state" in json_data:
                        #    if json_data["state"]["flags"]["error"]:
                        #        job_state = "error"
                        #    elif json_data["state"]["flags"]["paused"]:
                        #        job_state = "paused"
                        #    elif json_data["state"]["flags"]["printing"]:
                        #        job_state = "printing"
                        #    elif json_data["state"]["flags"]["ready"]:
                        #        job_state = "ready"
                        print_job.updateState(print_job_state)
                        
                        #progress = json_data["progress"]["completion"]
                        if "done" in json_data[0]:
                            progress = json_data[0]["done"]
                        if "start" in json_data[0]:
                            if json_data[0]["start"]:
                                ##self.setTimeElapsed(json_data[0]["start"])
                                ##self.setTimeElapsed(datetime.datetime.fromtimestamp(json_data[0]["start"]).strftime('%Y-%m-%d %H:%M:%S'))
                                if json_data[0]["printTime"]:
                                    print_job.updateTimeTotal(json_data[0]["printTime"])
                                if json_data[0]["printedTimeComp"]:
                                    print_job.updateTimeElapsed(json_data[0]["printedTimeComp"])
                                elif progress > 0:
                                    print_job.updateTimeTotal(json_data[0]["printTime"] * (progress / 100))
                                else:
                                    print_job.updateTimeTotal(0)
                            else:
                                print_job.updateTimeElapsed(0)
                                print_job.updateTimeTotal(0)
                            print_job.updateName(json_data[0]["job"])
                    #except:
                    #    if printer:
                    #        printer.activePrintJob.updateState("offline")
                    #        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} configuration is invalid").format(self._key))
                else:
                    if printer:
                        printer.activePrintJob.updateState("offline")
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Repetier on {0} bad response").format(self._key))
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
                        Logger.log("d", "Set Repetier camera url to %s", self._camera_url)
                        if self._camera_url != "" and len(self._printers) > 0:
                            self._printers[0].setCamera(NetworkCamera(self._camera_url))
                        self._camera_rotation = 180
                        self._camera_mirror = False
                        #self.cameraOrientationChanged.emit()

        elif reply.operation() == QNetworkAccessManager.PostOperation:
            if self._api_prefix + "?a=listModels" in reply.url().toString():  # Result from /files command:
                if http_status_code == 201:
                    Logger.log("d", "Resource created on Repetier instance: %s", reply.header(QNetworkRequest.LocationHeader).toString())
                else:
                    pass  # TODO: Handle errors

                reply.uploadProgress.disconnect(self._onUploadProgress)
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
                    message.actionTriggered.connect(self._onMessageActionTriggered)
                    message.show()

            elif self._api_prefix + "?a=send" in reply.url().toString():  # Result from /job command:
                if http_status_code == 204:
                    Logger.log("d", "Repetier command accepted")
                else:
                    pass  # TODO: Handle errors

        else:
            Logger.log("d", "RepetierOutputDevice got an unhandled operation %s", reply.operation())

    def _onUploadProgress(self, bytes_sent, bytes_total):
        if bytes_total > 0:
            # Treat upload progress as response. Uploading can take more than 10 seconds, so if we don't, we can get
            # timeout responses if this happens.
            self._last_response_time = time()

            progress = bytes_sent / bytes_total * 100            
            if progress < 100:
                if progress > self._progress_message.getProgress():
                    self._progress_message.setProgress(progress)
            else:
                self._progress_message.hide()
                self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Storing data on Repetier"), 0, False, -1)
                self._progress_message.show()
        else:
            self._progress_message.setProgress(0)

    def _createPrinterList(self):
        printer = PrinterOutputModel(output_controller=self._output_controller, number_of_extruders=self._number_of_extruders)
        if self._camera_url != "":
            printer.setCamera(NetworkCamera(self._camera_url))
        printer.updateName(self.name)
        self._printers = [printer]
        self.printersChanged.emit()

    def _onMessageActionTriggered(self, message, action):
        if action == "open_browser":
            QDesktopServices.openUrl(QUrl(self._base_url))
