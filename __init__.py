# Copyright (c) 2015 Ultimaker B.V.
# Cura is released under the terms of the AGPLv3 or higher.
import os, json

from . import RepetierOutputDevicePlugin
from . import DiscoverRepetierAction

from UM.Version import Version
from UM.Application import Application
from UM.Logger import Logger
from UM.i18n import i18nCatalog
i18n_catalog = i18nCatalog("cura")

def getMetaData():
    return {
        "stage": {
            "name": i18n_catalog.i18nc("@item:inmenu", "RepetierPlugin"),
            "weight": 1
        }
}

def register(app):
    if __matchVersion():
        return {
        "output_device": RepetierOutputDevicePlugin.RepetierOutputDevicePlugin(),
        "machine_action": DiscoverRepetierAction.DiscoverRepetierAction()
        }
		
def __matchVersion():
    cura_version = Application.getInstance().getVersion()
    if cura_version == "master":
        Logger.log("d", "Running Cura from source, ignoring version of the plugin")
        return True
    cura_version = Version(cura_version)

    # Get version information from plugin.json
    plugin_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")
    try:
        with open(plugin_file_path) as plugin_file:
            plugin_info = json.load(plugin_file)
            plugin_version = Version(plugin_info["version"])
    except:
        Logger.log("w", "Could not get version information for the plugin")
        return False

    if plugin_version.getMajor() == cura_version.getMajor() and plugin_version.getMinor() == cura_version.getMinor():
        return True
    else:
        return False