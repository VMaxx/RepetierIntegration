# RepetierIntegration
# Version 4.1
# Shane Bumpurs
Cura plugin which enables printing directly to Repetier and monitoring the progress
The name has changed to RepetierIntegration in the plugin folder.
This plugin is basically a copy of the Octoprint plugin with the necessary changes to work with repetier server.


Installation
----
* Manually:
  - Make sure your Cura version is 4.0+
  - Download or clone the repository into [Cura installation folder]/plugins/RepetierIntegration
    or in the plugins folder inside the configuration folder. The configuration folder can be
    found via Help -> Show Configuration Folder inside Cura.
    NB: The folder of the plugin itself *must* be ```RepetierIntegration```
    NB: Make sure you download the branch that matches the Cura branch (ie: 3.1 for Cura 2.2-3.1, 3.2 for Cura 3.2, 3.3 for Cura 3.3 etc)

Blurry youtube video of install
https://youtu.be/VHw93Pt_QIo

How to use
----
- Make sure Repetier is up and running
- In Cura, under Manage printers select your printer.
- Select "Connect to Repetier" on the Manage Printers page.
- Click add and make sure you match the Name you give it in the plugin, with the name of the Printer in Cura.
- Fill in the IP and Port, if you have security turned on, click the advanced checkbox and enter that information
- Click Get Printers button, it should populate the dropdown to select your repetier printer.
- Click OK this will show the printer in the Printers list again but then ask for your Repetier API key.  Once that is filled you can check the extra options if you have a webcam and need to rotate it.
- If you do not want to print immediately but have your print job stored uncheck "Automatically start print job after uploading"
- From this point on, the print monitor should be functional and you should be able to switch to "Print to Repetier" on the bottom of the sidebar.
  
  Config example:
  ![alt text](https://user-images.githubusercontent.com/12956626/59142707-9d0d5e00-8987-11e9-94f7-53bc2707e3d1.jpg "Config") 
  
  Latest changes: Multiple printers now work.  Fixed issue with Repetier printer name not matching Cura printer name
  If you have security turned off, it will pull the apikey from the Repetier instance when you're setting up a new printer.
