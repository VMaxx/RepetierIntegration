project(RepetierIntegration NONE)
cmake_minimum_required(VERSION 2.8.12)

install(FILES
    __init__.py
    plugin.json
    DiscoverRepetierAction.py
    DiscoverRepetierAction.qml
    RepetierComponents.qml
    RepetierOutputDevice.py
    RepetierOutputDevicePlugin.py
    NetworkMJPGImage.py
    MonitorItem.qml
    LICENSE
    README.md
    DESTINATION lib/cura/plugins/RepetierIntegration
)
