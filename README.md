# RepetierPlugin
# Version 3.3
# Shane Bumpurs
Cura plugin which enables printing directly to Repetier and monitoring the progress

This plugin is basically a copy of the Octoprint plugin with the necessary changes to work with repetier server.

Installation
----
* Manually:
  - Make sure your Cura version is 3.3 there are significant changes from 3.2
  - Download or clone the repository into [Cura installation folder]/plugins/RepetierPlugin
    or in the plugins folder inside the configuration folder. The configuration folder can be
    found via Help -> Show Configuration Folder inside Cura.
    NB: The folder of the plugin itself *must* be ```RepetierPlugin```
    NB: Make sure you download the branch that matches the Cura branch (ie: 3.1 for Cura 2.2-3.1, 3.2 for Cura 3.2, 3.3 for Cura 3.3 etc)


How to use
----
- Make sure Repetier is up and running
- In Cura, add a Printer instance name that matches the 3d printer name you have added to Repetier.  The name of the instance _must_ match the printer.
- Select "Connect to Repetier" on the Manage Printers page.
- Select your Repetier instance from the list and enter the API key which is
  available in the Repetier settings.  If you've setup a userid and password you must click advanced and enter that information.
- From this point on, the print monitor should be functional and you should be
  able to switch to "Print to Repetier" on the bottom of the sidebar.

Issues
-----------
Print jobs are all showing as dummy until I can resolve the problem.
