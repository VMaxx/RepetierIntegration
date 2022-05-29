// Copyright (c) 2020 Aldo Hoeben / fieldOfView & Shane Bumpurs
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import UM 1.2 as UM
import Cura 1.0 as Cura

import QtQuick 2.2
import QtQuick.Controls 2.0

Item
{
    id: base

    property bool printerConnected: Cura.MachineManager.printerOutputDevices.length != 0
    property bool repetierConnected: printerConnected && Cura.MachineManager.printerOutputDevices[0].hasOwnProperty("repetierVersion")

    Cura.SecondaryButton
    {
        objectName: "openRepetierButton"
        height: UM.Theme.getSize("save_button_save_to_button").height
        tooltip: catalog.i18nc("@info:tooltip", "Open the Repetier web interface")
        text: catalog.i18nc("@action:button", "Open Repetier...")
        onClicked: manager.openWebPage(Cura.MachineManager.printerOutputDevices[0].baseURL)
        visible: repetierConnected
    }

    UM.I18nCatalog{id: catalog; name:"repetier"}
}