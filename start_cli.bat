@echo off
echo starting (terminal / CLI version)
python -m pip install --user SpeechRecognition sounddevice
python app_launcher.py
echo done
pause
exit
