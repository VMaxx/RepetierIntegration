import UM 1.2 as UM
import Cura 1.1 as Cura

import QtQuick 2.2
import QtQuick.Controls 1.1
import QtQuick.Controls 2.15 as QQC2
import QtQuick.Layouts 1.1
import QtQuick.Window 2.1
import QtQuick.Dialogs 1.1

Cura.MachineAction
{
    id: base
    anchors.fill: parent;
    property var selectedInstance: null
    property string activeMachineId:
    {
        if (Cura.MachineManager.activeMachineId != undefined)
        {
            return Cura.MachineManager.activeMachineId;
        }
        else if (Cura.MachineManager.activeMachine !== null)
        {
            return Cura.MachineManager.activeMachine.id;
        }

        CuraApplication.log("There does not seem to be an active machine");
        return "";
    }

    onVisibleChanged:
    {
        if(!visible)
        {
            manager.cancelApiKeyRequest();
        }
    }

    function boolCheck(value) //Hack to ensure a good match between python and qml.
    {
        if(value == "True")
        {
            return true
        }else if(value == "False" || value == undefined)
        {
            return false
        }
        else
        {
            return value
        }
    }
    Column
    {
        anchors.fill: parent;
        id: discoverRepetierAction


        spacing: UM.Theme.getSize("default_margin").height
        width: parent.width

        SystemPalette { id: palette }
        UM.I18nCatalog { id: catalog; name:"cura" }

        Item
        {
            width: parent.width
            height: pageTitle.height

            Label
            {
                id: pageTitle
                text: catalog.i18nc("@title", "Connect to Repetier")
                wrapMode: Text.WordWrap
                font.pointSize: 18
            }

            Label
            {
                id: pluginVersion
                anchors.bottom: pageTitle.bottom
                anchors.right: parent.right
                text: manager.pluginVersion
                wrapMode: Text.WordWrap
                font.pointSize: 8
            }
        }
        Label
        {
            id: pageDescription
            width: parent.width
            wrapMode: Text.WordWrap
            text: catalog.i18nc("@label", "Select your Repetier instance from the list below:")
        }

        Row
        {
            spacing: UM.Theme.getSize("default_lining").width

            Button
            {
                id: addButton
                text: catalog.i18nc("@action:button", "Add");
                onClicked:
                {
                    manualPrinterDialog.showDialog("", "192.168.1.250", "3344", "/", false, "", "","");
                }
            }

            Button
            {
                id: editButton
                text: catalog.i18nc("@action:button", "Edit")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked:
                {
                    manualPrinterDialog.showDialog(
                        base.selectedInstance.name, base.selectedInstance.ipAddress,
                        base.selectedInstance.port, base.selectedInstance.path,
                        base.selectedInstance.getProperty("useHttps") == "true",
                        base.selectedInstance.getProperty("userName"), base.selectedInstance.getProperty("password"),Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id")
                    );
                }
            }

            Button
            {
                id: removeButton
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked: manager.removeManualInstance(base.selectedInstance.name)
            }

            Button
            {
                id: rediscoverButton
                text: catalog.i18nc("@action:button", "Refresh")
                onClicked: manager.startDiscovery()
            }
        }

        Row
        {
            width: parent.width
            spacing: UM.Theme.getSize("default_margin").width

            Item
            {
                width: Math.floor(parent.width * 0.4)
                height: base.height - parent.y

                ScrollView
                {
                    id: objectListContainer
                    frameVisible: true
                    width: parent.width
                    anchors.top: parent.top
                    anchors.bottom: objectListFooter.top
                    anchors.bottomMargin: UM.Theme.getSize("default_margin").height

                    Rectangle
                    {
                        parent: viewport
                        anchors.fill: parent
                        color: palette.light
                    }

                    ListView
                    {
                        id: listview
                        model: manager.discoveredInstances
                        onModelChanged:
                        {
                            var selectedId = manager.getInstanceId();
                            for(var i = 0; i < model.length; i++) {
                                if(model[i].getId() == selectedId)
                                {
                                    currentIndex = i;
                                    return
                                }
                            }
                            currentIndex = -1;
                        }
                        width: parent.width
                        currentIndex: activeIndex
                        onCurrentIndexChanged:
                        {
                            base.selectedInstance = listview.model[currentIndex];
                            apiCheckDelay.throttledCheck();
                        }
                        Component.onCompleted: manager.startDiscovery()
                        delegate: Rectangle
                        {
                            height: childrenRect.height
                            color: ListView.isCurrentItem ? palette.highlight : index % 2 ? palette.base : palette.alternateBase
                            width: parent.width
                            Label
                            {
                                anchors.left: parent.left
                                anchors.leftMargin: UM.Theme.getSize("default_margin").width
                                anchors.right: parent.right
                                text: listview.model[index].name
                                color: parent.ListView.isCurrentItem ? palette.highlightedText : palette.text
                                elide: Text.ElideRight
                                font.italic: listview.model[index].key == manager.instanceId
                            }

                            MouseArea
                            {
                                anchors.fill: parent;
                                onClicked:
                                {
                                    if(!parent.ListView.isCurrentItem)
                                    {
                                        parent.ListView.view.currentIndex = index;
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Column
            {
                width: Math.floor(parent.width * 0.6)    
                spacing: UM.Theme.getSize("default_margin").height
                Label
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: base.selectedInstance ? base.selectedInstance.name : ""
                    font.pointSize: 16
                    elide: Text.ElideRight
                }
                Grid
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    columns: 2
                    rowSpacing: UM.Theme.getSize("default_lining").height
                    verticalItemAlignment: Grid.AlignVCenter
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Version")
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? base.selectedInstance.repetierVersion : ""
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)    
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Address")
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.7)    
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? "%1:%2".arg(base.selectedInstance.ipAddress).arg(String(base.selectedInstance.port)) : ""
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)    
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "RepetierID")
                    }
                    Label
                    {
                        id: lblRepID
                        width: Math.floor(parent.width * 0.2)    
                        text: base.selectedInstance ? Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id") : ""
                    }                    
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)    
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "API Key")
                    }
                    TextField
                    {
                        id: apiKey
                        width: Math.floor(parent.width * 0.8 - UM.Theme.getSize("default_margin").width)                            
                        text: base.selectedInstance ? Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_api_key") : ""
                        onTextChanged:
                        {
                            apiCheckDelay.throttledCheck()
                        }
                    }
                    Connections
                    {
                        target: base
                        onSelectedInstanceChanged:
                        {
                            if(base.selectedInstance != null)
							{
								lblRepID.text = Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id")
								apiKey.text = Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_api_key")
								//apiKey.text = manager.getApiKey(base.selectedInstance.getId())
							}
                        }
                    }
                    Timer
                    {
                        id: apiCheckDelay
                        interval: 500

                        signal throttledCheck
                        signal check
                        property bool checkOnTrigger: false

                        onThrottledCheck:
                        {
                            if(running)
                            {
                                checkOnTrigger = true;
                            }
                            else
                            {
                                check();
                            }
                        }
                        onCheck:
                        {  
                            if(base.selectedInstance != null)
                            if(base.selectedInstance.baseURL != null)
                            {
                                 manager.testApiKey(base.selectedInstance.getId(),base.selectedInstance.baseURL, apiKey.text, base.selectedInstance.getProperty("userName"), base.selectedInstance.getProperty("password"), lblRepID.text)
                                 checkOnTrigger = false;
                                 restart();
                            }
                        }
                        onTriggered:
                        {
                            if(checkOnTrigger)
                            {
                                check();
                            }
                        }
                    }
                }

                Label
                {
                    visible: base.selectedInstance != null && text != ""
                    text:
                    {
                        var result = ""
                        if (apiKey.text == "")
                        {
                            result = catalog.i18nc("@label", "Please enter the API key to access Repetier.");
                        }
                        else
                        {
                            if(manager.instanceResponded)
                            {
                                if(manager.instanceApiKeyAccepted)
                                {
                                    return "";
                                }
                                else
                                {
                                    result = catalog.i18nc("@label", "The API key is not valid.");
                                }
                            }
                            else
                            {
                                return catalog.i18nc("@label", "Repetier printer name hasn't been selected, please edit and click get printers and choose the correct name from the drop down list.")
                            }
                        }
                        result += " " + catalog.i18nc("@label", "You can get the API key through the Repetier web page.");
                        return result;
                    }
                    width: parent.width - UM.Theme.getSize("default_margin").width
                    wrapMode: Text.WordWrap
                }

                Column
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    spacing: UM.Theme.getSize("default_lining").height

                    CheckBox
                    {
                        id: autoPrintCheckBox
                        text: catalog.i18nc("@label", "Automatically start print job after uploading")
                        enabled: manager.instanceApiKeyAccepted
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_auto_print") != "false"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_auto_print", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: showCameraCheckBox
                        text: catalog.i18nc("@label", "Show webcam image")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_show_camera") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_show_camera", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: flipYCheckBox
                        text: catalog.i18nc("@label", "Flip Webcam Y")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamflip_y") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamflip_y", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: flipXCheckBox
                        text: catalog.i18nc("@label", "Flip Webcam X")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamflip_x") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamflip_x", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: rot90CheckBox
                        text: catalog.i18nc("@label", "Rotate Webcam 90")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_90") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_90", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: rot180CheckBox
                        text: catalog.i18nc("@label", "Rotate Webcam 180")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_180") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_180", String(checked))
                        }
                    }                    
                    CheckBox
                    {
                        id: rot270CheckBox
                        text: catalog.i18nc("@label", "Rotate Webcam 270")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_270") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_webcamrot_270", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: storeOnSdCheckBox
                        text: catalog.i18nc("@label", "Store G-code on the printer SD card")
                        enabled: manager.instanceSupportsSd
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_sd") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_sd", String(checked))
                        }
                    }
                    Label
                    {
                        visible: storeOnSdCheckBox.checked
                        wrapMode: Text.WordWrap
                        width: parent.width
                        text: catalog.i18nc("@label", "Note: Transfering files to the printer SD card takes very long. Using this option is not recommended.")
                    }
                    CheckBox
                    {
                        id: fixGcodeFlavor
                        text: catalog.i18nc("@label", "Set Gcode flavor to \"Marlin\"")
                        checked: true
                        visible: machineGCodeFlavorProvider.properties.value == "UltiGCode"
                    }
                    Label
                    {
                        text: catalog.i18nc("@label", "Note: Printing UltiGCode using Repetier does not work. Setting Gcode flavor to \"Marlin\" fixes this, but overrides material settings on your printer.")
                        width: parent.width - UM.Theme.getSize("default_margin").width
                        wrapMode: Text.WordWrap
                        visible: fixGcodeFlavor.visible
                    }
                }

                Flow
                {
                    visible: base.selectedInstance != null
                    spacing: UM.Theme.getSize("default_margin").width

                    Button
                    {
                        text: catalog.i18nc("@action", "Open in browser...")
                        onClicked: manager.openWebPage(base.selectedInstance.baseURL)
                    }

                    Button
                    {
                        text: catalog.i18nc("@action:button", "Connect")
                        enabled: apiKey.text != "" && manager.instanceApiKeyAccepted
                        onClicked:
                        {
                            if(fixGcodeFlavor.visible)
                            {
                                manager.applyGcodeFlavorFix(fixGcodeFlavor.checked)
                            }							
                            manager.setInstanceId(base.selectedInstance.repetier_id)
                            manager.setApiKey(apiKey.text)
                            completed()
                        }
                    }                
                }
            }
        }
    }

    UM.SettingPropertyProvider
    {
        id: machineGCodeFlavorProvider

        containerStackId: Cura.MachineManager.activeMachine.id
        key: "machine_gcode_flavor"
        watchedProperties: [ "value" ]
        storeIndex: 4
    }
    UM.Dialog
    {
        id: manualPrinterDialog
        property string oldName
        property alias nameText: nameField.text
        property alias addressText: addressField.text
        property alias portText: portField.text
        property alias pathText: pathField.text
        property alias userNameText: userNameField.text
        property alias passwordText: passwordField.text
        property alias repidText: repid.editText
        property alias selrepidText: repid.currentText

        title: catalog.i18nc("@title:window", "Manually added Repetier instance")

        minimumWidth: 400 * screenScaleFactor
        minimumHeight: (showAdvancedOptions.checked ? 340 : 220) * screenScaleFactor
        width: minimumWidth
        height: minimumHeight		

        signal showDialog(string name, string address, string port, string path_, bool useHttps, string userName, string password, string repetierid)
        onShowDialog:
        {
            oldName = name;
            nameText = name;
            nameField.selectAll();
            nameField.focus = true;

            addressText = address;
            portText = port;
            pathText = path_;
            httpsCheckbox.checked = useHttps;
            userNameText = userName;
            passwordText = password;
            repidText = repetierid;			
            manualPrinterDialog.show();
        }

        onAccepted:
        {
            if(oldName != nameText)
            {
                manager.removeManualInstance(oldName);
            }
            if(portText == "")
            {
                portText = "3344" // default http port
            }
            if(pathText.substr(0,1) != "/")
            {
                pathText = "/" + pathText // ensure absolute path
            }
            manager.setManualInstance(nameText, addressText, parseInt(portText), pathText, httpsCheckbox.checked, userNameText, passwordText, repidText)
			manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_id", repidText)
        }

        Column {
            anchors.fill: parent
            spacing: UM.Theme.getSize("default_margin").height

            Grid
            {
                columns: 2
                width: parent.width
                verticalItemAlignment: Grid.AlignVCenter
                rowSpacing: UM.Theme.getSize("default_lining").height

                Label
                {
                    text: catalog.i18nc("@label","Instance Name")
                    width: Math.floor(parent.width * 0.4)    
                }

                TextField
                {
                    id: nameField
                    maximumLength: 20
                    width: Math.floor(parent.width * 0.6)    
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_ \']*/
                    }
                }

                Label
                {
                    text: catalog.i18nc("@label","IP Address or Hostname")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: addressField
                    maximumLength: 253
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_]*/
                    }
                }

                Label
                {
                    text: catalog.i18nc("@label","Port Number")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: portField
                    maximumLength: 5
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[0-9]*/
                    }
                }
                Label
                {
                    text: catalog.i18nc("@label","Path")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: pathField
                    maximumLength: 30
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_\/]*/
                    }
                }
                Button
                {
                text: catalog.i18nc("@action:button","Get Printers")
                onClicked:
                    {
                        manager.getPrinterList(manualPrinterDialog.addressText.trim()+":"+manualPrinterDialog.portText.trim())
                        if (manager.getPrinters.length>0)
                            {
                                comboPrinters.clear()
                                for (var i =0;i<manager.getPrinters.length;i++)
                                    if(comboPrinters[i] != "")
                                        comboPrinters.append({ label: catalog.i18nc("@action:ComboBox option", manager.getPrinters[i]), key: manager.getPrinters[i] })
                            }                        
                    }
                }
                Label
                {
                    text: catalog.i18nc("@label","")
                    width: Math.floor(parent.width * 0.4)    
                }                

                Label
                {
                    text: catalog.i18nc("@label","Printer")
                    width: Math.floor(parent.width * 0.4)    
                }

                QQC2.ComboBox
                {
                    model: ListModel
                    {
                        id: comboPrinters						
                    }
                    currentIndex:
                    {
                        var currentValue = propertyProvider.properties.value;
                        var index = 0;
                        for(var i = 0; i < comboPrinters.length; i++)
                        {
							if ( typeof comboPrinters.get(i).key !== "undefined" )
								if(comboPrinters.get(i).key == currentValue) {
									index = i;
									break;
                            }
                        }
                        return index
                    }
					onCurrentIndexChanged:
						{
						if ( typeof comboPrinters.get(currentIndex).key !== "undefined" )
							editText=comboPrinters.get(currentIndex).key
						}
                    textRole: "label"
                    editable: false
                    id: repid
                    width: Math.floor(parent.width * 0.4)
                }
            }


            CheckBox
            {
                id: showAdvancedOptions
                text: catalog.i18nc("@label","Show security options (advanced)")
            }

            Grid
            {
                columns: 2
                visible: showAdvancedOptions.checked
                width: parent.width
                verticalItemAlignment: Grid.AlignVCenter
                rowSpacing: UM.Theme.getSize("default_lining").height

                Label
                {
                    text: catalog.i18nc("@label","Use HTTPS")
                    width: Math.floor(parent.width * 0.4)
                }

                CheckBox
                {
                    id: httpsCheckbox
                }

                Label
                {
                    text: catalog.i18nc("@label","HTTP user name")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: userNameField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                }

                Label
                {
                    text: catalog.i18nc("@label","HTTP password")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: passwordField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                    echoMode: TextInput.PasswordEchoOnEdit
                }


            }

            Label
            {
                visible: showAdvancedOptions.checked
                wrapMode: Text.WordWrap
                width: parent.width
                text: catalog.i18nc("@label","These options are to authenticate to the Repetier server if you have security setup.")

            }
        }

        rightButtons: [
            Button {
                text: catalog.i18nc("@action:button","Cancel")
                onClicked:
                {
                    manualPrinterDialog.reject()
                    manualPrinterDialog.hide()
                }
            },
            Button {
                text: catalog.i18nc("@action:button", "Ok")
                onClicked:
                {
                    manualPrinterDialog.accept()
                    manualPrinterDialog.hide()
                }
                enabled: manualPrinterDialog.nameText.trim() != "" && manualPrinterDialog.addressText.trim() != "" && manualPrinterDialog.portText.trim() != "" && manualPrinterDialog.repidText.trim() != ""
                isDefault: true
            }
        ]
    }
}
