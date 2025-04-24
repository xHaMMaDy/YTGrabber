import os
import sys
import subprocess

def build():
    # Get the absolute path to the assets directory
    assets_dir = os.path.abspath("assets")
    
    # Build the command to run PyInstaller with UI
    cmd = [
        'pyinstaller',
        'src/main.py',
        '--name=YTGrabber',
        '--windowed',
        '--onefile',
        '--add-data', f'{assets_dir};assets',
        '--icon=assets/youtube_logo.ico',
        '--clean',
        '--noconfirm',  # Don't ask for confirmation before overwriting
        '--exclude-module', 'PyQt5',  # Exclude PyQt5
        '--exclude-module', 'PyQt6',  # Exclude PyQt6 as well
    ]
    
    # Run PyInstaller with UI
    subprocess.run(cmd)

if __name__ == "__main__":
    build() 