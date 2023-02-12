rmdir /s /q nado.build
rmdir /s /q nado.dist
python versioner.py
python -m nuitka nado.py --standalone --windows-icon-from-ico=graphics\icon.ico --include-package=pympler
xcopy /i /y version nado.dist
xcopy /e /i /y templates nado.dist\templates
xcopy /e /i /y static nado.dist\static
xcopy /e /i /y graphics nado.dist\graphics
"C:\Program Files (x86)\Inno Setup 6\iscc" /q "setup.iss"
pause
