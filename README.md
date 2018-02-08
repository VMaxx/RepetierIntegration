# RepetierPlugin
# Version 3.2
# Shane Bumpurs
Cura plugin which enables printing directly to Repetier and monitoring the progress

This plugin is basically a copy of the Octoprint plugin with the necessary changes to work with repetier server.

Installation
----
* Manually:
  - Make sure your Cura version is 3.2
  - Download or clone the repository into [Cura installation folder]/plugins/RepetierPlugin
    or in the plugins folder inside the configuration folder. The configuration folder can be
    found via Help -> Show Configuration Folder inside Cura.
    NB: The folder of the plugin itself *must* be ```RepetierPlugin```
    NB: Make sure you download the branch that matches the Cura branch (ie: 2.4 for Cura 2.4 etc)


How to use
----
- Make sure Repetier is up and running
- In Cura, add a Printer matching the 3d printer you have connected to Repetier.  The name of the instance must match the printer.
- Select "Connect to Repetier" on the Manage Printers page.
- Select your Repetier instance from the list and enter the API key which is
  available in the Repetier settings.  If you've setup a userid and password you must click advanced and enter that information.
- From this point on, the print monitor should be functional and you should be
  able to switch to "Print to Repetier" on the bottom of the sidebar.

Issues
----
I only have one printer connected to my repetier server, so I didn't code it for more than one.
