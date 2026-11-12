PM7 Cloud Preview Fixer includes third-party software:

- Python (Python Software Foundation license): https://docs.python.org/3/license.html
- Pillow (MIT-CMU and bundled component licenses): https://github.com/python-pillow/Pillow
- PySide6, Shiboken6, and Qt (LGPLv3/GPL/commercial, as applicable to each included module):
  https://www.qt.io/licensing/open-source-lgpl-obligations
- PyInstaller bootloader (GPL with distribution exception): https://pyinstaller.org/en/stable/license.html

Collected license texts are installed in the `licenses` directory and included in the portable
executable. The Python/Qt/Pillow libraries are bundled without modifications. The application uses
Qt Core, Gui, and Widgets with dynamically linked DLLs. It does not use WebEngine or Qt Network.
Application source and the reproducible PyInstaller build recipe accompany this repository.
PyInstaller's archive viewer can inspect and extract the packaged libraries. Users may rebuild
with modified libraries; the application imposes no signature check or technical restriction on
replacement. No commercial Qt license is claimed. Anycubic, Lychee, and CHITUBOX names are used only
to describe file compatibility; this application is not affiliated with those vendors.
