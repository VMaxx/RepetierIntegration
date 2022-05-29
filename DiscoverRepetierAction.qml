import QtQuick 2.1
import QtQuick.Controls 2.0

import UM 1.5 as UM
import Cura 1.0 as Cura

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

        UM.I18nCatalog { id: catalog; name:"repetier" }

        Item
        {
            width: parent.width
            height: pageTitle.height

            UM.Label
            {
                id: pageTitle
                text: catalog.i18nc("@title", "Connect to Repetier")
                font: UM.Theme.getFont("large_bold")
            }

            UM.Label
            {
                id: pluginVersion
                anchors.bottom: pageTitle.bottom
                anchors.right: parent.right
                text: manager.pluginVersion
                wrapMode: Text.WordWrap
                font.pointSize: 8
            }
        }
        UM.Label
        {
            id: pageDescription
            width: parent.width
            wrapMode: Text.WordWrap
            text: catalog.i18nc("@label", "Select your Repetier instance from the list below:")
        }

        Row
        {
            spacing: UM.Theme.getSize("default_lining").width

            Cura.SecondaryButton
            {
                id: addButton
                text: catalog.i18nc("@action:button", "Add");
                onClicked:
                {
                    manualPrinterDialog.showDialog("", "192.168.1.250", "3344", "/", false, "", "","");
                }
            }

            Cura.SecondaryButton
            {
                id: editButton
                text: catalog.i18nc("@action:button", "Edit")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked:
                {
					if (Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id") != null)
						{
						manualPrinterDialog.showDialog(
							base.selectedInstance.name, base.selectedInstance.ipAddress,
							base.selectedInstance.port, base.selectedInstance.path,
							base.selectedInstance.getProperty("useHttps") == "true",						
							base.selectedInstance.getProperty("userName"), 
							base.selectedInstance.getProperty("password"), 
							Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id")							
						);
						}
					else
						{
						manualPrinterDialog.showDialog(
							base.selectedInstance.name, base.selectedInstance.ipAddress,
							base.selectedInstance.port, base.selectedInstance.path,
							base.selectedInstance.getProperty("useHttps") == "true",						
							base.selectedInstance.getProperty("userName"), 
							base.selectedInstance.getProperty("password"), 
							""
						);
						}
                }
            }

            Cura.SecondaryButton
            {
                id: removeButton
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked: manager.removeManualInstance(base.selectedInstance.name)
            }

            Cura.SecondaryButton
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

            Rectangle
            {
                width: Math.floor(parent.width * 0.4)
                height: base.height - (parent.y + UM.Theme.getSize("default_margin").height)

                color: UM.Theme.getColor("main_background")
                border.width: UM.Theme.getSize("default_lining").width
                border.color: UM.Theme.getColor("thick_lining")

                ListView
                {
                    id: listview

                    clip: true
                    ScrollBar.vertical: UM.ScrollBar {}

                    anchors.fill: parent
                    anchors.margins: UM.Theme.getSize("default_lining").width

                    model: manager.discoveredInstances
                    onModelChanged:
                    {
                        var selectedId = manager.instanceId;
                        for(var i = 0; i < model.length; i++) {
                            if(model[i].getId() == selectedId)
                            {
                                currentIndex = i;
                                return
                            }
                        }
                        currentIndex = -1;
                    }

                    currentIndex: activeIndex
                    onCurrentIndexChanged:
                    {
                        base.selectedInstance = listview.model[currentIndex];
                        apiCheckDelay.throttledCheck();
						comboGroups.clear();
                    }

                    Component.onCompleted: manager.startDiscovery()

                    delegate: Rectangle
                    {
                        height: childrenRect.height
                        color: ListView.isCurrentItem ? UM.Theme.getColor("text_selection") : UM.Theme.getColor("main_background")
                        width: parent.width
                        UM.Label
                        {
                            anchors.left: parent.left
                            anchors.leftMargin: UM.Theme.getSize("default_margin").width
                            anchors.right: parent.right
                            text: listview.model[index].name
                            elide: Text.ElideRight
                            font.italic: listview.model[index].key == manager.instanceId
                            wrapMode: Text.NoWrap
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

            Column
            {
                width: Math.floor(parent.width * 0.6)
                spacing: UM.Theme.getSize("default_margin").height
                UM.Label
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: base.selectedInstance ? base.selectedInstance.name : ""
                    font: UM.Theme.getFont("large_bold")
                    elide: Text.ElideRight
                }
                Grid
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    columns: 2
                    rowSpacing: UM.Theme.getSize("default_lining").height
                    verticalItemAlignment: Grid.AlignVCenter
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Version")
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? base.selectedInstance.repetierVersion : ""
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Address")
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.7)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? "%1:%2".arg(base.selectedInstance.ipAddress).arg(String(base.selectedInstance.port)) : ""
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "RepetierID")
                    }
                    UM.Label
                    {
                        id: lblRepID
                        width: Math.floor(parent.width * 0.2)    
                        text: base.selectedInstance ? Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_id") : ""
                    }                    
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)    
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "API Key")
                    }
                    Cura.TextField
                    {
                        id: apiKey
                        width: Math.floor(parent.width * 0.8 - UM.Theme.getSize("default_margin").width)                            
                        text: base.selectedInstance ? Cura.ContainerManager.getContainerMetaDataEntry(base.selectedInstance.name, "repetier_api_key") : ""
                        onTextChanged:
                        {
                            apiCheckDelay.throttledCheck()
							comboGroups.clear()
                        }
                    }
                    Connections
                    {
                        target: base
                        function onSelectedInstanceChanged()
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

                        property bool checkOnTrigger: false

                        function throttledCheck()
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
                        function check()
                        {
                            if(base.selectedInstance != null)
                            if(base.selectedInstance.baseURL != null)
                            {								
                                manager.testApiKey(base.selectedInstance.getId(),base.selectedInstance.baseURL, apiKey.text, base.selectedInstance.getProperty("userName"), base.selectedInstance.getProperty("password"), lblRepID.text);
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

                UM.Label
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
                            if(manager.instanceInError)
                            {
                                return catalog.i18nc("@label", "Repetier is not available.")
                            }
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

                    UM.CheckBox
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
                    UM.CheckBox
                    {
                        id: storeAndPrintCheckBox
                        text: catalog.i18nc("@label", "Store print job and print")
                        enabled: manager.instanceApiKeyAccepted
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_print") != "false"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_print", String(checked))
                        }
                    }
                    Cura.ComboBox
                    {
						id: comboGroupsctl
						property bool populatingModel: false
                        textRole: "label"
                        editable: false                        
                        width: Math.floor(parent.width * 0.4)
						
                        model: ListModel
                        {
                            id: comboGroups
							
							Component.onCompleted: populateModel()
							
							function populateModel()
							{
								comboGroupsctl.populatingModel = true;									
								var add = true											
								for (var i = 0; i < manager.getGroups.length; i++)
									{																								
									for (var m = 0; m < comboGroups.count; m++)											
										{																										
										if(comboGroups.get(m).key==manager.getGroups[i])
											{														
											add=false;
											}
										}
									if(add==true)
										{
										if(manager.getGroups[i] != "")
											{
											comboGroups.append({ label: catalog.i18nc("@action:ComboBox option", manager.getGroups[i]), key: manager.getGroups[i] });																											
											}
										}													
									}
								var current_index = -1;
								if (Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_group") != undefined)
									{	
										if (manager.getGroups.length > 0)
											for(var i = 0; i < manager.getGroups.length; i++)
											{	if(comboGroups.get(i) != undefined)										
												if(comboGroups.get(i).key == Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_group"))
												{
													current_index = i;
												}
											}										
									}
								comboGroupsctl.currentIndex = current_index;
								comboGroupsctl.populatingModel = false;								
							}
                        }						
                        currentIndex:
                        {
							if (( activeIndex !== undefined )&&( comboGroups !== undefined ))
							{								
								var currentValue = comboGroups.model[activeIndex]
								var index = 0
								for(var i = 0; i < comboGroups.length; i++)
								{
									if ( typeof comboGroups.get(i).key !== undefined )
										if( comboGroups.get(i).key == currentValue ) {
											index = i
											break
									}
								}
								return index								
							}						
                        }
                        onCurrentIndexChanged:
						{
						if ( typeof comboGroups.get(currentIndex).key !== undefined )
							{
							currentText = comboGroups.get(currentIndex).key
							manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachine.id, "repetier_store_group", currentText)
							}
						}
                    }
					Timer
                    {
                        id: groupTimer
                        interval: 500; running: true; repeat: true

                        function check()
                        {							
							if(base.selectedInstance != null)
							{
								if ((base.selectedInstance.baseURL.trim() != "") && (apiKey.text.trim() != ""))
								{	
									if (manager.getGroups != undefined)
									{										
										if (manager.getGroups.length > 0)
										{
											comboGroups.populateModel();
										}
									}
								}
							}							
                        }
                        onTriggered:
                        {
							check();
                        }
                    }		
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.CheckBox
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
                    UM.Label
                    {
                        visible: storeOnSdCheckBox.checked
                        wrapMode: Text.WordWrap
                        width: parent.width
                        text: catalog.i18nc("@label", "Note: Transfering files to the printer SD card takes very long. Using this option is not recommended.")
                    }
                    UM.CheckBox
                    {
                        id: fixGcodeFlavor
                        text: catalog.i18nc("@label", "Set Gcode flavor to \"Marlin\"")
                        checked: true
                        visible: machineGCodeFlavorProvider.properties.value == "UltiGCode"
                    }
                    UM.Label
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

                    Cura.SecondaryButton
                    {
                        text: catalog.i18nc("@action", "Open in browser...")
                        onClicked: manager.openWebPage(base.selectedInstance.baseURL)
                    }

                    Cura.SecondaryButton
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

                UM.Label
                {
                    text: catalog.i18nc("@label","Instance Name")
                    width: Math.floor(parent.width * 0.4)    
                }

                Cura.TextField
                {
                    id: nameField
                    maximumLength: 20
                    width: Math.floor(parent.width * 0.6)                        
                }

                UM.Label
                {
                    text: catalog.i18nc("@label","IP Address or Hostname")
                    width: Math.floor(parent.width * 0.4)
                }

                Cura.TextField
                {
                    id: addressField
                    maximumLength: 253
                    width: Math.floor(parent.width * 0.6)
                }

                UM.Label
                {
                    text: catalog.i18nc("@label","Port Number")
                    width: Math.floor(parent.width * 0.4)
                }

                Cura.TextField
                {
                    id: portField
                    maximumLength: 5
                    width: Math.floor(parent.width * 0.6)
                }
                UM.Label
                {
                    text: catalog.i18nc("@label","Path")
                    width: Math.floor(parent.width * 0.4)
                }

                Cura.TextField
                {
                    id: pathField
                    maximumLength: 30
                    width: Math.floor(parent.width * 0.6)
                }
                Cura.SecondaryButton
                {
                text: catalog.i18nc("@action:button","Get Printers")
                onClicked:
                    {
                        manager.getPrinterList("http://" + manualPrinterDialog.addressText.trim()+":"+manualPrinterDialog.portText.trim()+"/")
                        if (manager.getPrinters.length>0)
                            {
                                comboPrinters.clear()
                                for (var i =0;i<manager.getPrinters.length;i++)
                                    if(comboPrinters[i] != "")
                                        comboPrinters.append({ label: catalog.i18nc("@action:ComboBox option", manager.getPrinters[i]), key: manager.getPrinters[i] })
                            }                        
                    }
                }
                UM.Label
                {
                    text: catalog.i18nc("@label","")
                    width: Math.floor(parent.width * 0.4)    
                }                

                UM.Label
                {
                    text: catalog.i18nc("@label","Printer")
                    width: Math.floor(parent.width * 0.4)    
                }

                Cura.ComboBox
                {
                    model: ListModel
                    {
                        id: comboPrinters                        
                    }
                    currentIndex:
                    {
                        var currentValue = comboPrinters[currentIndex]
                        var index = 0
                        for(var i = 0; i < comboPrinters.length; i++)
                        {
                            if ( typeof comboPrinters.get(i).key != undefined )
                                if(comboPrinters.get(i).key == currentValue) {
                                    index = i
                                    break
                            }
                        }
                        return index
                    }
                    onCurrentIndexChanged:
                        {
						if (comboPrinters.get(currentIndex) != undefined)
							if ( typeof comboPrinters.get(currentIndex).key != undefined )
								currentText=comboPrinters.get(currentIndex).key
                        }
                    textRole: "label"
                    editable: false
                    id: repid
                    width: Math.floor(parent.width * 0.4)
                }
            }


            UM.CheckBox
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

                UM.Label
                {
                    text: catalog.i18nc("@label","Use HTTPS")
                    width: Math.floor(parent.width * 0.4)
                }

                UM.CheckBox
                {
                    id: httpsCheckbox
                }

                UM.Label
                {
                    text: catalog.i18nc("@label","HTTP user name")
                    width: Math.floor(parent.width * 0.4)
                }

                Cura.TextField
                {
                    id: userNameField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                }

                UM.Label
                {
                    text: catalog.i18nc("@label","HTTP password")
                    width: Math.floor(parent.width * 0.4)
                }

                Cura.TextField
                {
                    id: passwordField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                    echoMode: TextInput.PasswordEchoOnEdit
                }


            }

            UM.Label
            {
                visible: showAdvancedOptions.checked
                wrapMode: Text.WordWrap
                width: parent.width
                text: catalog.i18nc("@label","These options are to authenticate to the Repetier server if you have security setup.")

            }
        }

        rightButtons: [
            Cura.SecondaryButton {
                text: catalog.i18nc("@action:button","Cancel")
                onClicked:
                {
                    manualPrinterDialog.reject()
                    manualPrinterDialog.hide()
                }
            },
            Cura.PrimaryButton {
                text: catalog.i18nc("@action:button", "Ok")
                onClicked:
                {
                    manualPrinterDialog.accept()
                    manualPrinterDialog.hide()
                }
                enabled: manualPrinterDialog.nameText.trim() != "" && manualPrinterDialog.addressText.trim() != "" && manualPrinterDialog.portText.trim() != "" && manualPrinterDialog.repidText.trim() != ""
            }
        ]
    }
}
