# RepetierIntegration
# Version 5.2
Mick Mifsud

### 🛠️ Bugfixed by Claude — connection setup now works as expected

The connect-a-new-printer flow used to be flaky (API key not sticking, printer selection resetting,
repeated delete/re-add just to get a connection). Those issues have been found and fixed; see the
git history for details. Ordinary use once connected was never affected.

Cura plugin which enables printing directly to Repetier and monitoring the progress
The name has changed to RepetierIntegration in the plugin folder.
This plugin is basically a copy of the Octoprint plugin with the necessary changes to work with repetier server.
Updated to 5.1, this version will not work with 5.0+.

Installation
----
* Manually:
  - Make sure your Cura version is 5.0+
  - Download or clone the repository into [Cura installation folder]/plugins/RepetierIntegration
    or in the plugins folder inside the configuration folder. The configuration folder can be
    found via Help -> Show Configuration Folder inside Cura.
    NB: The folder of the plugin itself *must* be ```RepetierIntegration```
    NB: Make sure you download the branch that matches the Cura branch (ie: 3.1 for Cura 2.2-3.1, 3.2 for Cura 3.2, 3.3 for Cura 3.3 etc)

Blurry Youtube Video showing Install
https://youtu.be/VHw93Pt_QIo

How to use
----
- Make sure Repetier is up and running
- In Cura, under Manage printers select your printer.
- Select "Connect to Repetier" on the Manage Printers page.
- Click add, fill in the IP and Port, if you have security turned on, click the advanced checkbox and enter that information
- Click Get Printers button, it should populate the dropdown to select your repetier printer.
- Click OK this will show the printer in the Printers list again but then ask for your Repetier API key.  Once that is filled you can check the extra options if you have a webcam and need to rotate it.
- Once the API key is accepted, the "Connect" button becomes available — click it to link this Repetier instance to the current Cura printer (the linked instance is shown in bold in the list).
- If you do not want to print immediately but have your print job stored uncheck "Automatically start print job after uploading"
- From this point on, the print monitor should be functional and you should be able to switch to "Print to Repetier" on the bottom of the sidebar.
