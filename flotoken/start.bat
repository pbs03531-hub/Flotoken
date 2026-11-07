@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo Flotoken is starting. Open http://127.0.0.1:5000 in your browser.
echo First time: tap "Flotoken team" at the bottom, create YOUR owner login, then Restaurants - Add restaurant.
echo Press Ctrl+C to stop.
python app.py
pause
