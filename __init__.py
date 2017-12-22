# Copyright (c) 2015 Ultimaker B.V.
# Cura is released under the terms of the AGPLv3 or higher.
from . import RepetierOutputDevicePlugin
from . import DiscoverRepetierAction
from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

def getMetaData():
    return {}

def register(app):
    return {
        "output_device": RepetierOutputDevicePlugin.RepetierOutputDevicePlugin(),
        "machine_action": DiscoverRepetierAction.DiscoverRepetierAction()
    }