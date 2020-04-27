# Copyright (c) 2019 Aldo Hoeben / fieldOfView & Shane Bumpurs
# RepetierIntegration is released under the terms of the AGPLv3 or higher.
import os, json

from . import RepetierOutputDevicePlugin
from . import DiscoverRepetierAction
from . import NetworkMJPGImage

from UM.Version import Version
from UM.Application import Application
from UM.Logger import Logger

from PyQt5.QtQml import qmlRegisterType
def getMetaData():
    return {}

def register(app):
    qmlRegisterType(NetworkMJPGImage.NetworkMJPGImage, "RepetierIntegration", 1, 0, "NetworkMJPGImage")
        return {
	        "output_device": RepetierOutputDevicePlugin.RepetierOutputDevicePlugin(),
	        "machine_action": DiscoverRepetierAction.DiscoverRepetierAction()
        }    