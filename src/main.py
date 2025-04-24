# v1.0.0 – 2025-04-20
"""
YTGrabber v1.0.0 – Enhanced with playlist support & fixed trimming
-----------------------------------------------------------
Tested on PySide6 6.7, Python 3.12, yt-dlp 2024.05.18.
"""

import os
import re
import sys
import csv
import time
import json
import subprocess
import logging
from datetime import datetime
from traceback import format_exc
from os.path import join
import tempfile

import requests
import qdarktheme as qdarktheme
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QUrl, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices, QFontDatabase, QFont
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog, QProgressBar,
    QTextEdit, QTabWidget, QMessageBox, QDialog, QCheckBox, QToolButton,
    QMenu, QTableWidget, QTableWidgetItem, QStackedWidget, QGroupBox, QStyle,
    QHeaderView, QSpinBox
)

# ----------------------------------------------------------------------------
# Logging configuration
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("YTGrabber")

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------

def get_startupinfo():
    """Get subprocess configuration to hide console window on Windows."""
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None

def is_valid_youtube_link(url: str) -> bool:
    """Very loose YouTube URL validator."""
    pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    return bool(re.match(pattern, url))


def is_youtube_playlist(url: str) -> bool:
    """Check if URL is a YouTube playlist."""
    pattern = r'^(https?://)?(www\.)?youtube\.com/playlist\?list=.+$'
    return bool(re.match(pattern, url))


def sanitize_filename(filename: str) -> str:
    """Strip characters that are illegal on most filesystems."""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()


def format_duration(duration) -> str:
    try:
        d = int(duration)
        return f"{d // 60} minutes {d % 60} seconds" if d >= 60 else f"{d} seconds"
    except (ValueError, TypeError):
        return str(duration)


def seconds_to_hhmmss(seconds: int | float) -> str:
    """Convert seconds to HH:MM:SS format."""
    if not seconds:
        return "00:00:00"
    # Convert to integer to ensure proper formatting
    seconds = int(seconds)
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def hhmmss_to_seconds(h: str) -> int:
    """Convert HH:MM:SS format to seconds."""
    try:
        if not h or h.strip() == "":
            return 0
        parts = h.split(":")
        if len(parts) == 3:
            hh, mm, ss = map(int, parts)
            return hh * 3600 + mm * 60 + ss
        elif len(parts) == 2:
            mm, ss = map(int, parts)
            return mm * 60 + ss
        else:
            return int(h)
    except (ValueError, TypeError):
        return 0


def format_filesize(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"


def format_speed(bytes_per_sec: float) -> str:
    """Format download speed in human-readable format."""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.1f} B/s"
    elif bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec/1024:.1f} KB/s"
    else:
        return f"{bytes_per_sec/(1024*1024):.1f} MB/s"


def total_bitrate_mbps(fmt: dict) -> float | None:
    """Return total bitrate in Mbps (float) or None if unknown"""
    kbps = fmt.get("tbr") or (fmt.get("vbr", 0) + fmt.get("abr", 0))
    return (kbps / 1000) if kbps else None


def size_bytes(fmt: dict, duration: int) -> int | None:
    """Return exact or estimated size in bytes, None if unavailable"""
    if fmt.get("filesize"):
        return int(fmt["filesize"])
    if fmt.get("filesize_approx"):
        return int(fmt["filesize_approx"])
    bitrate = total_bitrate_mbps(fmt)
    if bitrate and duration:
        return int(bitrate * 1_000_000 / 8 * duration)
    return None


def human_mb(size_bytes: int | float | None) -> str:
    """Convert bytes to human-readable MB format."""
    return "—" if not size_bytes else f"{size_bytes/1048576:.0f} MB"


def download_image_as_pixmap(url: str) -> QPixmap:
    """Download an image from URL and return as QPixmap with improved quality."""
    pix = QPixmap()
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        pix.loadFromData(r.content)
        
        # If the image is too small, try to enhance it
        if pix.width() < 320 or pix.height() < 180:
            return pix.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
    except requests.RequestException as e:
        logger.warning(f"Thumbnail download failed: {e}")
    return pix


def append_download_history(title: str, url: str, filepath: str, filesize: int):
    """Append a single row to local CSV history."""
    try:
        with open("download_history.csv", "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now().isoformat(), title, url, filepath, filesize])
    except IOError as e:
        logger.error(f"Failed to write history: {e}")


def get_direct_video_url(info: dict, format_id: str = None) -> str:
    """Get direct video URL from info dict, optionally filtering by format_id."""
    fmts = info.get("formats", [])
    
    if format_id:
        # If format_id is provided, find that specific format
        for f in fmts:
            if f.get("format_id") == format_id and f.get("url"):
                return f["url"]
        return ""
    else:
        # Otherwise return best quality progressive format
        valid = [f for f in fmts if f.get("vcodec") not in (None, "none") and 
                f.get("acodec") not in (None, "none") and f.get("url")]
        if not valid:
            valid = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("url")]
        if not valid:
            return ""
        valid.sort(key=lambda x: x.get("height", 0), reverse=True)
        return valid[0]["url"]


# ----------------------------------------------------------------------------
# Worker threads
# ----------------------------------------------------------------------------

class DownloadWorker(QThread):
    progress = Signal(int)
    progress_text = Signal(str)
    finished = Signal(str, int)
    error = Signal(str)
    paused = Signal(bool)
    speed_update = Signal(float, float)  # bytes/sec, ETA in seconds

    def __init__(self, url: str, output_filename: str, format_id: str, extra_options: dict,
                 settings: QSettings, is_audio_only: bool, parent=None):
        super().__init__(parent)
        self._url = url
        self._output_filename = output_filename
        self._format_id = format_id
        self._extra_options = extra_options or {}
        self._settings = settings
        self._is_audio_only = is_audio_only
        self._paused = False
        self._stop_flag = False
        self._process = None
        self._start_time = None
        self._downloaded_bytes = 0
        self._total_bytes = 0
        self._last_update_time = 0
        self._last_downloaded_bytes = 0

    def run(self):
        """Run the download process."""
        try:
            self.paused.emit(False)
            
            # Get FFmpeg path
            ffmpeg = get_ffmpeg_path()
            
            # Base command
            cmd = ["yt-dlp", "--newline"]
            
            # Use human-readable progress output
            cmd.append("--progress")
            
            # Add FFmpeg location
            cmd.extend(["--ffmpeg-location", ffmpeg])
            
            # Add format if specified
            if 'format' in self._extra_options:
                cmd.extend(["-f", self._extra_options.pop('format')])
            elif self._format_id:
                cmd.extend(["-f", self._format_id])
            
            # Add output template
            cmd.extend(["-o", self._output_filename])
            
            # Post processing options
            if not self._is_audio_only:
                # Video post-processing with AAC audio
                cmd.extend([
                    "--postprocessor-args", 
                    "ffmpeg:-c:a aac -b:a 192k -ar 48000 -c:v copy"
                ])
            else:
                # Audio-only post-processing with high quality
                cmd.extend([
                    "--postprocessor-args",
                    "ffmpeg:-c:a aac -b:a 256k -ar 48000"
                ])
            
            # Handle download rate limit
            rate_limit = self._settings.value("rate_limit", "0")
            if rate_limit and rate_limit != "0":
                cmd.extend(["--limit-rate", f"{rate_limit}K"])
            
            # Network settings
            timeout = self._settings.value("timeout", "10")
            cmd.extend(["--socket-timeout", timeout])
            
            # Proxy settings
            proxy = self._settings.value("proxy", "")
            if proxy:
                cmd.extend(["--proxy", proxy])
            
            # Geo-bypass if enabled
            if self._settings.value("geo_bypass", "false") == "true":
                cmd.append("--geo-bypass")
            
            # Add cookies if specified
            cookies_file = self._settings.value("cookies_file", "")
            if cookies_file and os.path.exists(cookies_file):
                cmd.extend(["--cookies", cookies_file])
            
            # Add retries
            retries = self._settings.value("retries", "10")
            cmd.extend(["--retries", retries])
            
            # Add any extra options
            for k, v in self._extra_options.items():
                if v is True:
                    cmd.append(f"--{k}")
                elif v is not False and v is not None:
                    cmd.extend([f"--{k}", str(v)])
            
            # Add URL
            cmd.append(self._url)
            
            self.progress_text.emit(f"Starting download with options: {' '.join(cmd)}")
            
            # Start the process
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                startupinfo=get_startupinfo()
            )
            
            self._start_time = time.time()
            self._last_update_time = time.time()
            self._last_bytes = 0
            
            # Process output
            while self._process.poll() is None:
                line = self._process.stdout.readline().strip()
                if line:
                    self._parse_progress(line)
            
            # Process remaining output
            for line in self._process.stdout:
                if line.strip():
                    self._parse_progress(line.strip())
            
            # Check return code
            if self._process.returncode != 0:
                self.error.emit(f"Download failed with return code {self._process.returncode}")
                return
            
            # Calculate final file size
            filesize = os.path.getsize(self._output_filename) if os.path.exists(self._output_filename) else 0
            self.finished.emit(self._output_filename, filesize)
            
        except Exception as e:
            error_msg = f"Download error: {str(e)}\n{format_exc()}"
            self.error.emit(error_msg)

    def _parse_progress(self, line):
        """Parse progress from yt-dlp output."""
        # Forward all lines to the progress text signal
        self.progress_text.emit(line)
        
        # Process downloading lines to extract progress percentage
        if "[download]" in line and "%" in line:
            # Extract percentage
            percent_match = re.search(r'(\d+\.\d+)%', line)
            if percent_match:
                percent = float(percent_match.group(1))
                self.progress.emit(int(percent))
            
            # Extract speed and ETA
            speed_match = re.search(r'at\s+([^\s]+)', line)
            eta_match = re.search(r'ETA\s+([^\s]+)', line)
            
            if speed_match:
                speed_str = speed_match.group(1)
                self.speed_update.emit(self._parse_speed(speed_str), 0)
            
            if eta_match:
                eta_str = eta_match.group(1)
                _, eta_seconds = self._parse_eta(eta_str)
                
                # Update speed info only if we have valid values
                if speed_match and eta_seconds > 0:
                    self.speed_update.emit(self._parse_speed(speed_match.group(1)), eta_seconds)
        
        # Handle post-processing progress
        elif "Merging" in line or "Converting" in line or "Post-processing" in line:
            self.progress.emit(95)  # Almost done
            
        elif "Deleting original file" in line:
            self.progress.emit(98)  # Nearly finished
    
    def _parse_speed(self, speed_str):
        """Parse download speed string to bytes per second."""
        try:
            if speed_str.endswith('/s'):
                speed_str = speed_str[:-2]
            
            if speed_str.endswith('KiB'):
                return float(speed_str[:-3]) * 1024
            elif speed_str.endswith('MiB'):
                return float(speed_str[:-3]) * 1024 * 1024
            elif speed_str.endswith('GiB'):
                return float(speed_str[:-3]) * 1024 * 1024 * 1024
            elif speed_str.endswith('B'):
                return float(speed_str[:-1])
            
            return 0
        except (ValueError, AttributeError):
            return 0
    
    def _parse_eta(self, eta_str):
        """Parse ETA string to seconds."""
        try:
            if eta_str == "Unknown":
                return "Unknown", 0
            
            parts = eta_str.split(':')
            if len(parts) == 3:  # HH:MM:SS
                h, m, s = map(int, parts)
                total_seconds = h * 3600 + m * 60 + s
                return eta_str, total_seconds
            elif len(parts) == 2:  # MM:SS
                m, s = map(int, parts)
                total_seconds = m * 60 + s
                return eta_str, total_seconds
            else:
                return eta_str, 0
        except (ValueError, AttributeError):
            return eta_str, 0

    def toggle_pause(self):
        """Toggle pause state of the download."""
        self._paused = not self._paused
        self.paused.emit(self._paused)

    def stop(self):
        """Stop the download."""
        self._stop_flag = True
        self._paused = False
        if self._process:
            try:
                self._process.terminate()
            except:
                pass


class TrimWorker(QThread):
    progress = Signal(int)
    progress_text = Signal(str)
    finished = Signal(str, int)
    error = Signal(str)

    def __init__(self, yt_url, output_path, start_time, end_time, parent=None):
        super().__init__(parent)
        self._yt_url = yt_url
        self._output = output_path
        self._start = start_time
        self._end = end_time
        self._stop_flag = False

    def run(self):
        """Run the trim process."""
        try:
            # Get FFmpeg path
            ffmpeg = get_ffmpeg_path()
            
            # Create temp directory for processing
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Get temp file paths
                tmp_vid_full = os.path.join(tmp_dir, "full_video.mp4")
                tmp_aud_full = os.path.join(tmp_dir, "full_audio.m4a")
                trimmed_vid = os.path.join(tmp_dir, "trimmed_video.mp4")
                trimmed_aud = os.path.join(tmp_dir, "trimmed_audio.m4a")
                
                self.progress.emit(5)
                self.progress_text.emit(f"Downloading full video from {self._yt_url}")
                
                # Download video stream
                video_cmd = [
                    "yt-dlp", "--newline",
                    "-f", "bestvideo[ext=mp4]",
                    "-o", tmp_vid_full,
                    "--no-playlist",
                    self._yt_url
                ]
                
                video_process = subprocess.Popen(
                    video_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    startupinfo=get_startupinfo()
                )
                
                # Process output
                for line in video_process.stdout:
                    self.progress_text.emit(line.strip())
                
                video_process.wait()
                
                if video_process.returncode != 0:
                    self.error.emit(f"Video download failed with code {video_process.returncode}")
                    return
                
                self.progress.emit(40)
                self.progress_text.emit("Downloading audio stream")
                
                # Download audio stream with high quality
                audio_cmd = [
                    "yt-dlp", "--newline",
                    "-f", "bestaudio[ext=m4a]",
                    "-o", tmp_aud_full,
                    "--no-playlist",
                    self._yt_url
                ]
                
                audio_process = subprocess.Popen(
                    audio_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    startupinfo=get_startupinfo()
                )
                
                # Process output
                for line in audio_process.stdout:
                    self.progress_text.emit(line.strip())
                
                audio_process.wait()
                
                if audio_process.returncode != 0:
                    self.error.emit(f"Audio download failed with code {audio_process.returncode}")
                    return
                
                self.progress.emit(70)
                self.progress_text.emit(f"Trimming video from {self._start} to {self._end}")
                
                # Trim video (using copy codec for efficiency)
                subprocess.run([
                    ffmpeg, '-y', '-ss', self._start, '-to', self._end, 
                    '-i', tmp_vid_full, '-c:v', 'copy', '-an', trimmed_vid
                ], check=True, startupinfo=get_startupinfo())
                
                # Trim audio
                subprocess.run([
                    ffmpeg, '-y', '-ss', self._start, '-to', self._end, 
                    '-i', tmp_aud_full, '-c:a', 'copy', '-vn', trimmed_aud
                ], check=True, startupinfo=get_startupinfo())
                
                # Merge video and audio with high quality AAC
                subprocess.run([
                    ffmpeg, '-y', '-i', trimmed_vid, '-i', trimmed_aud, 
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                    '-strict', 'experimental', self._output
                ], check=True, startupinfo=get_startupinfo())
                
                self.progress.emit(100)
                
                # Get file size
                filesize = os.path.getsize(self._output)
                self.finished.emit(self._output, filesize)
                
        except Exception as e:
            error_msg = f"Trim error: {str(e)}\n{format_exc()}"
            self.error.emit(error_msg)
            
    def stop(self):
        """Stop the trim process."""
        self.error.emit("Trim operation cancelled.")


class FetchInfoWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            self.progress.emit("Fetching video information...")
            
            # Create a temporary file for the JSON output
            tmp_file = f"info_{int(time.time())}.json"
            
            # Run yt-dlp to get video info
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-playlist",  # Don't process playlists yet
                self._url
            ]
            
            result = subprocess.run(cmd, 
                                 capture_output=True, 
                                 text=True, 
                                 check=True,
                                 startupinfo=get_startupinfo())
            
            # Parse the JSON output
            info = json.loads(result.stdout)
            
            # Emit the finished signal with the info dictionary
            self.finished.emit(info)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error fetching video info: {e.stderr}")
            self.error.emit(f"Failed to fetch video info: {e.stderr}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing video info: {e}")
            self.error.emit(f"Failed to parse video info: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.error.emit(f"Unexpected error: {str(e)}")


class FetchPlaylistInfoWorker(QThread):
    finished = Signal(list)
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            self.progress.emit("Fetching playlist information...")
            
            # Run yt-dlp to get playlist info
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--flat-playlist",  # Don't download video info for each video
                self._url
            ]
            
            result = subprocess.run(cmd, 
                                 capture_output=True, 
                                 text=True, 
                                 check=True,
                                 startupinfo=get_startupinfo())
            
            # Parse the JSON output (one JSON object per line)
            videos = []
            for line in result.stdout.splitlines():
                if line.strip():
                    video_info = json.loads(line)
                    videos.append(video_info)
            
            # Emit the finished signal with the list of videos
            self.finished.emit(videos)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error fetching playlist info: {e.stderr}")
            self.error.emit(f"Failed to fetch playlist info: {e.stderr}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing playlist info: {e}")
            self.error.emit(f"Failed to parse playlist info: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.error.emit(f"Unexpected error: {str(e)}")


# ----------------------------------------------------------------------------
# Custom title bar
# ----------------------------------------------------------------------------

class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self._click_pos = None
        self._start_pos = None
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(12)

        # Logo and title container
        logo_title_container = QHBoxLayout()
        logo_title_container.setSpacing(8)

        # Use icon instead of SVG
        icon_path = get_resource_path(os.path.join("assets", "youtube_logo.ico"))
        if os.path.exists(icon_path):
            logo_label = QLabel()
            logo_pixmap = QIcon(icon_path).pixmap(QSize(24, 24))
            logo_label.setPixmap(logo_pixmap)
            logo_label.setFixedSize(32, 32)
            logo_label.setAlignment(Qt.AlignCenter)
        else:
            logo_label = QLabel("▶")
            logo_label.setStyleSheet("""
                QLabel {
                    color: #c5160a;
                    font-size: 24px;
                    font-weight: bold;
                    padding: 2px;
                    min-width: 32px;
                    min-height: 32px;
                }
            """)
        logo_title_container.addWidget(logo_label)

        # Title
        title_lbl = QLabel("YTGrabber")
        title_lbl.setStyleSheet("""
            QLabel {
                color: #c5160a;
                font-size: 18px;
                font-weight: bold;
                padding-left: 5px;
            }
        """)
        logo_title_container.addWidget(title_lbl)
        logo_title_container.addStretch()
        
        layout.addLayout(logo_title_container)
        layout.addStretch()

        # Control buttons container
        control_container = QHBoxLayout()
        control_container.setSpacing(10)

        # Theme toggle button
        self.theme_btn = QPushButton()
        self.theme_btn.setFixedSize(40, 40)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self._parent._toggle_theme)
        self.theme_btn.setStyleSheet("""
            QPushButton {
                color: #c5160a;
                background: transparent;
                border: none;
                font-size: 22px;  # Increased font size for emoji
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: rgba(197, 22, 10, 0.1);
                border-radius: 5px;
            }
        """)
        # Add this line to set the initial emoji
        self._update_theme_button()  # Set the initial theme button text
        control_container.addWidget(self.theme_btn)

        # Menu button
        menu_btn = QToolButton()
        menu_btn.setText("≡")
        menu_btn.setStyleSheet("""
            QToolButton {
                color: #c5160a;
                background: transparent;
                border: none;
                padding: 5px;
                font-size: 24px;
            }
            QToolButton:hover {
                background: rgba(197, 22, 10, 0.1);
                border-radius: 5px;
            }
            QToolButton:pressed {
                background: rgba(197, 22, 10, 0.2);
            }
            QToolButton::menu-indicator { 
                image: none;
            }
        """)
        menu_btn.setCursor(Qt.PointingHandCursor)
        menu_btn.setFixedSize(40, 40)
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        
        # Create menu with dynamic theme-aware styling
        menu = QMenu(self)
        self._update_menu_style(menu)
        
        # Settings submenu
        settings_menu = QMenu("Settings", menu)
        self._update_menu_style(settings_menu)
        settings_menu.addAction("General Settings", self._parent._open_settings_dialog)
        settings_menu.addAction("Download Settings", self._parent._open_download_settings)
        settings_menu.addAction("Network Settings", self._parent._open_network_settings)
        settings_menu.addAction("UI Settings", self._parent._open_ui_settings)
        menu.addMenu(settings_menu)
        
        # Tools submenu
        tools_menu = QMenu("Tools", menu)
        self._update_menu_style(tools_menu)
        tools_menu.addAction("Export Logs", self._parent._export_logs)
        tools_menu.addAction("Clear History", self._parent._clear_history)
        tools_menu.addAction("Check for Updates", self._parent._check_updates)
        menu.addMenu(tools_menu)
        
        menu.addSeparator()
        menu.addAction("About", self._show_about)
        
        menu_btn.setMenu(menu)
        control_container.addWidget(menu_btn)

        # Window control buttons
        for txt, cb, hover_color in [
            ("−", self._parent.showMinimized, "rgba(197, 22, 10, 0.1)"),
            ("□", self._toggle_max_restore, "rgba(197, 22, 10, 0.1)"),
            ("×", self._parent.close, "rgba(197, 22, 10, 0.2)")
        ]:
            btn = QPushButton(txt)
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: #c5160a;
                    background: transparent;
                    border: none;
                    font-size: 18px;
                    font-family: Arial;
                    padding-bottom: 2px;
                }}
                QPushButton:hover {{
                    background: {hover_color};
                    border-radius: 5px;
                }}
            """)
            btn.clicked.connect(cb)
            control_container.addWidget(btn)

        layout.addLayout(control_container)

    def _update_menu_style(self, menu):
        """Update menu styling based on current theme."""
        is_dark = self._parent._settings.value("theme", "dark") == "dark"
        bg_color = "#202124" if is_dark else "#ffffff"
        hover_bg = "rgba(197, 22, 10, 0.1)"
        border_color = "#c5160a"
        
        menu.setStyleSheet(f"""
            QMenu {{
                color: #c5160a;
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 5px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 30px 8px 20px;
                border-radius: 3px;
                margin: 2px;
                font-size: 14px;
            }}
            QMenu::item:selected {{
                background-color: {hover_bg};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border_color};
                margin: 5px 15px;
            }}
            QMenu::item:disabled {{
                color: #666666;
            }}
        """)

    def _update_theme_button(self):
        """Update theme button appearance based on current theme."""
        is_dark = self._parent._settings.value("theme", "dark") == "dark"
        self.theme_btn.setText("🌜" if is_dark else "☀️")
        self.theme_btn.setStyleSheet("""
            QPushButton {
                color: #c5160a;
                background: transparent;
                border: none;
                font-size: 22px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: rgba(197, 22, 10, 0.1);
                border-radius: 5px;
            }
        """)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._click_pos = ev.globalPosition().toPoint()
            self._start_pos = self._parent.pos()

    def mouseMoveEvent(self, ev):
        if self._click_pos:
            delta = ev.globalPosition().toPoint() - self._click_pos
            self._parent.move(self._start_pos + delta)

    def mouseReleaseEvent(self, ev):
        self._click_pos = None

    def _toggle_max_restore(self):
        if self._parent.isMaximized():
            self._parent.showNormal()
        else:
            self._parent.showMaximized()

    def _show_about(self):
        """Show the About dialog."""
        about_text = """
        <h2 style='color:#c5160a;'>YTGrabber</h2>
        <p>Version 1.0.0</p>
        <p>A powerful YouTube video downloader with advanced features.</p>
        <p>by Ibrahim Hammad (HaMMaDy)</p>
        <p>GitHub: <a href='https://github.com/xHaMMaDy'>@xHaMMaDy</a></p>
        <p>Features:</p>
        <ul>
            <li>Download videos in various formats and qualities</li>
            <li>Download audio only</li>
            <li>Trim videos</li>
            <li>Download playlists</li>
            <li>Batch download</li>
            <li>Download history tracking</li>
        </ul>
        """
        
        dialog = QDialog(self)
        dialog.setWindowTitle("About YTGrabber")
        layout = QVBoxLayout(dialog)
        
        text_label = QLabel(about_text)
        text_label.setOpenExternalLinks(True)
        layout.addWidget(text_label)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()


# ----------------------------------------------------------------------------
# Settings dialog
# ----------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(900, 400)
        self._settings = QSettings("MyCompany", "YTGrabber")

        layout = QVBoxLayout(self)
        
        # Create tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # General settings tab
        general_tab = QWidget()
        general_layout = QFormLayout(general_tab)
        
        # Update default output directory
        default_output_dir = get_app_root()
        self.output_dir_edit = QLineEdit(self._settings.value("output_dir", default_output_dir))
        output_dir_row = QHBoxLayout()
        output_dir_row.addWidget(self.output_dir_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_output_dir)
        output_dir_row.addWidget(browse_btn)
        general_layout.addRow("Output directory:", output_dir_row)
        
        self.timeout_edit = QSpinBox()
        self.timeout_edit.setRange(5, 300)
        self.timeout_edit.setValue(int(self._settings.value("timeout", "10")))
        self.timeout_edit.setSuffix(" seconds")
        general_layout.addRow("Network timeout:", self.timeout_edit)
        
        self.verbose_chk = QCheckBox("Enable verbose logging")
        self.verbose_chk.setChecked(self._settings.value("verbose", "false") == "true")
        general_layout.addRow("", self.verbose_chk)
        
        self.auto_trim_chk = QCheckBox("Auto-enable trimming for long videos (>30 min)")
        self.auto_trim_chk.setChecked(self._settings.value("auto_trim", "false") == "true")
        general_layout.addRow("", self.auto_trim_chk)
        
        tabs.addTab(general_tab, "General")
        
        # Network settings tab
        network_tab = QWidget()
        network_layout = QFormLayout(network_tab)
        
        self.proxy_edit = QLineEdit(self._settings.value("proxy", ""))
        self.proxy_edit.setPlaceholderText("http://user:pass@host:port")
        network_layout.addRow("Proxy:", self.proxy_edit)
        
        self.cookies_file_edit = QLineEdit(self._settings.value("cookies_file", ""))
        cookies_row = QHBoxLayout()
        cookies_row.addWidget(self.cookies_file_edit)
        cookies_browse_btn = QPushButton("Browse")
        cookies_browse_btn.clicked.connect(self._browse_cookies_file)
        cookies_row.addWidget(cookies_browse_btn)
        network_layout.addRow("Cookies file:", cookies_row)
        
        self.geo_bypass_chk = QCheckBox("Enable geo-restriction bypass")
        self.geo_bypass_chk.setChecked(self._settings.value("geo_bypass", "false") == "true")
        network_layout.addRow("", self.geo_bypass_chk)
        
        tabs.addTab(network_tab, "Network")
        
        # Download settings tab
        download_tab = QWidget()
        download_layout = QFormLayout(download_tab)
        
        self.max_downloads_spin = QSpinBox()
        self.max_downloads_spin.setRange(1, 10)
        self.max_downloads_spin.setValue(int(self._settings.value("max_concurrent_downloads", "2")))
        download_layout.addRow("Max concurrent downloads:", self.max_downloads_spin)
        
        self.limit_rate_edit = QLineEdit(self._settings.value("limit_rate", ""))
        self.limit_rate_edit.setPlaceholderText("e.g., 1M, 500K (leave blank for no limit)")
        download_layout.addRow("Limit download rate:", self.limit_rate_edit)
        
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(int(self._settings.value("retries", "3")))
        download_layout.addRow("Retry attempts:", self.retries_spin)
        
        tabs.addTab(download_tab, "Download")
        
        # Buttons
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.output_dir_edit.text()
        )
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def _browse_cookies_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Cookies File", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            self.cookies_file_edit.setText(file_path)

    def accept(self):
        # Save general settings
        self._settings.setValue("output_dir", self.output_dir_edit.text())
        self._settings.setValue("timeout", str(self.timeout_edit.value()))
        self._settings.setValue("verbose", "true" if self.verbose_chk.isChecked() else "false")
        self._settings.setValue("auto_trim", "true" if self.auto_trim_chk.isChecked() else "false")
        
        # Save network settings
        self._settings.setValue("proxy", self.proxy_edit.text())
        self._settings.setValue("cookies_file", self.cookies_file_edit.text())
        self._settings.setValue("geo_bypass", "true" if self.geo_bypass_chk.isChecked() else "false")
        
        # Save download settings
        self._settings.setValue("max_concurrent_downloads", str(self.max_downloads_spin.value()))
        self._settings.setValue("limit_rate", self.limit_rate_edit.text())
        self._settings.setValue("retries", str(self.retries_spin.value()))
        
        super().accept()


# ----------------------------------------------------------------------------
# Main application window
# ----------------------------------------------------------------------------

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(600, 400)
        self.setWindowTitle("YTGrabber")
        self._settings = QSettings("MyCompany", "YTGrabber")
        
        # Set window icon
        icon_path = get_resource_path(os.path.join("assets", "youtube_logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Always set dark theme as default
        self._settings.setValue("theme", "dark")

        # Initialize state variables
        self._video_info = None
        self._playlist_info = None
        self._workers = []
        self._current_worker = None
        self._download_queue = []
        self._active_downloads = 0
        self._max_concurrent_downloads = int(self._settings.value("max_concurrent_downloads", "2"))

        # Set up main layout
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Add custom title bar
        self._title_bar = CustomTitleBar(self)
        self._title_bar.setFixedHeight(40)
        main_layout.addWidget(self._title_bar)

        # Apply theme after title bar is created
        self._apply_theme()

        # Add tab widget
        self._tabs = QTabWidget()
        main_layout.addWidget(self._tabs)
        self.setCentralWidget(main)
        self.statusBar().showMessage("Ready")

        # Build tabs
        self._build_single_tab()
        self._build_playlist_tab()
        self._build_batch_tab()
        self._build_history_tab()
        
        # Connect tab change signal
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        # Set up timer for queue processing
        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._process_download_queue)
        self._queue_timer.start(1000)  # Check queue every second

    def _on_tab_changed(self, index):
        """Handle tab change events."""
        tab_text = self._tabs.tabText(index)
        if tab_text == "Download History":
            self._load_history()

    def _build_single_tab(self):
        """Build the single video download tab."""
        tab = QWidget()
        self._tabs.addTab(tab, "Single Download")
        L = QVBoxLayout(tab)

        # URL entry
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("YouTube URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Enter YouTube video URL here")
        url_row.addWidget(self.url_edit)
        self.fetch_btn = QPushButton("Fetch Info", clicked=self._fetch_info)
        self.fetch_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        url_row.addWidget(self.fetch_btn)
        L.addLayout(url_row)

        # Video info group
        info_grp = QGroupBox("Video Info")
        info_form = QFormLayout()
        self.title_lbl = QLabel("N/A")
        self.channel_lbl = QLabel("N/A")
        self.duration_lbl = QLabel("N/A")
        self.upload_lbl = QLabel("N/A")
        info_form.addRow("Title:", self.title_lbl)
        info_form.addRow("Channel:", self.channel_lbl)
        info_form.addRow("Duration:", self.duration_lbl)
        info_form.addRow("Upload Date:", self.upload_lbl)
        info_grp.setLayout(info_form)
        L.addWidget(info_grp)

        # Thumbnail group
        thumb_grp = QGroupBox("Thumbnail")
        thumb_layout = QVBoxLayout()
        self.thumb_label = QLabel()
        self.thumb_label.setMinimumSize(240, 135)  # Reduced from 320x180
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setProperty("class", "thumbnail-placeholder")  # Add class for styling
        thumb_layout.addWidget(self.thumb_label)
        
        # Button row for thumbnail actions
        thumb_btn_row = QHBoxLayout()
        preview_btn = QPushButton("Preview", clicked=self._preview_thumb)
        preview_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #c5160a;
                border: 1px solid #c5160a;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgba(197, 22, 10, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(197, 22, 10, 0.2);
            }
        """)
        save_thumb_btn = QPushButton("Save Thumbnail", clicked=self._save_thumbnail)
        save_thumb_btn.setStyleSheet(preview_btn.styleSheet())  # Use same style as preview button
        thumb_btn_row.addWidget(preview_btn)
        thumb_btn_row.addWidget(save_thumb_btn)
        thumb_layout.addLayout(thumb_btn_row)
        
        thumb_grp.setLayout(thumb_layout)
        L.addWidget(thumb_grp)

        # Download options
        dl_grp = QGroupBox("Download Options")
        dl_form = QFormLayout()

        self.dl_type_combo = QComboBox()
        self.dl_type_combo.addItems(["Video Download", "Audio Only"])
        self.dl_type_combo.currentIndexChanged.connect(self._update_format_combo)
        dl_form.addRow("Download type:", self.dl_type_combo)

        self.fmt_combo = QComboBox()
        dl_form.addRow("Format:", self.fmt_combo)

        # Trimming controls
        self.trim_chk = QCheckBox("Enable trimming")
        self.trim_chk.toggled.connect(self._toggle_trim_enabled)
        dl_form.addRow("", self.trim_chk)

        self.trim_start_edit = QLineEdit("00:00:00")
        self.trim_start_edit.setToolTip("HH:MM:SS – leave blank to start from 00:00:00")
        self.trim_end_edit = QLineEdit()
        self.trim_end_edit.setPlaceholderText("Leave blank for video end")
        self.trim_end_edit.setToolTip("HH:MM:SS – leave blank to keep until video end")
        dl_form.addRow("Trim start:", self.trim_start_edit)
        dl_form.addRow("Trim end:", self.trim_end_edit)
        
        # Disable trimming controls by default
        self._toggle_trim_enabled(False)

        # Output directory
        default_output_dir = os.getcwd()  # Use current working directory
        self._settings.setValue("output_dir", default_output_dir)  # Always set the current directory
        self.output_dir_edit = QLineEdit(default_output_dir)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_dir_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(lambda: self._browse_output_dir(self.output_dir_edit))
        out_row.addWidget(browse_btn)
        dl_form.addRow("Output directory:", out_row)

        # Download buttons
        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("Download", clicked=self._start_download)
        self.download_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        btn_row.addWidget(self.download_btn)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        btn_row.addWidget(self.pause_btn)
        dl_form.addRow(btn_row)
        dl_grp.setLayout(dl_form)
        L.addWidget(dl_grp)

        # Progress section
        progress_grp = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(3)  # Reduced spacing
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(15)  # Reduced height
        progress_layout.addWidget(self.progress_bar)
        
        # Speed and ETA labels
        speed_layout = QHBoxLayout()
        speed_layout.setSpacing(3)  # Reduced spacing
        self.speed_lbl = QLabel("Speed: --")
        self.eta_lbl = QLabel("ETA: --")
        speed_layout.addWidget(self.speed_lbl)
        speed_layout.addWidget(self.eta_lbl)
        progress_layout.addLayout(speed_layout)
        
        # Log text area
        self.log_te = QTextEdit()
        self.log_te.setReadOnly(True)
        self.log_te.setFixedHeight(80)  # Reduced height
        progress_layout.addWidget(self.log_te)
        
        progress_grp.setLayout(progress_layout)
        L.addWidget(progress_grp)

    def _build_playlist_tab(self):
        """Build the playlist download tab."""
        tab = QWidget()
        self._tabs.addTab(tab, "Playlist Download")
        L = QVBoxLayout(tab)

        # URL entry
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Playlist URL:"))
        self.playlist_url_edit = QLineEdit()
        self.playlist_url_edit.setPlaceholderText("Enter YouTube playlist URL here")
        url_row.addWidget(self.playlist_url_edit)
        self.fetch_playlist_btn = QPushButton("Fetch Playlist", clicked=self._fetch_playlist_info)
        self.fetch_playlist_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        url_row.addWidget(self.fetch_playlist_btn)
        L.addLayout(url_row)

        # Playlist info group
        playlist_info_grp = QGroupBox("Playlist Info")
        playlist_info_layout = QFormLayout()
        self.playlist_title_lbl = QLabel("N/A")
        self.playlist_count_lbl = QLabel("N/A")
        playlist_info_layout.addRow("Title:", self.playlist_title_lbl)
        playlist_info_layout.addRow("Videos:", self.playlist_count_lbl)
        playlist_info_grp.setLayout(playlist_info_layout)
        L.addWidget(playlist_info_grp)

        # Videos table
        self.playlist_table = QTableWidget(0, 4)
        self.playlist_table.setHorizontalHeaderLabels(["Title", "Duration", "Status", "Select"])
        self.playlist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.playlist_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.playlist_table.verticalHeader().setDefaultSectionSize(25)  # Reduced row height
        L.addWidget(self.playlist_table)

        # Download options
        playlist_dl_grp = QGroupBox("Download Options")
        playlist_dl_form = QFormLayout()
        playlist_dl_form.setSpacing(3)  # Reduced spacing

        self.playlist_dl_type_combo = QComboBox()
        self.playlist_dl_type_combo.addItems(["Video Download", "Audio Only"])
        playlist_dl_form.addRow("Download type:", self.playlist_dl_type_combo)

        self.playlist_quality_combo = QComboBox()
        self.playlist_quality_combo.addItems(["Best", "1080p", "720p", "480p", "360p", "Smallest"])
        playlist_dl_form.addRow("Quality:", self.playlist_quality_combo)

        # Selection controls
        selection_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all_playlist_videos)
        selection_row.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all_playlist_videos)
        selection_row.addWidget(deselect_all_btn)
        
        invert_selection_btn = QPushButton("Invert Selection")
        invert_selection_btn.clicked.connect(self._invert_playlist_selection)
        selection_row.addWidget(invert_selection_btn)
        
        playlist_dl_form.addRow("Selection:", selection_row)

        # Output directory
        default_output_dir = os.getcwd()  # Use current working directory
        self._settings.setValue("output_dir", default_output_dir)  # Always set the current directory
        self.playlist_output_dir_edit = QLineEdit(default_output_dir)
        playlist_out_row = QHBoxLayout()
        playlist_out_row.addWidget(self.playlist_output_dir_edit)
        playlist_browse_btn = QPushButton("Browse")
        playlist_browse_btn.clicked.connect(lambda: self._browse_output_dir(self.playlist_output_dir_edit))
        playlist_out_row.addWidget(playlist_browse_btn)
        playlist_dl_form.addRow("Output directory:", playlist_out_row)

        # Create subfolder option
        self.create_subfolder_chk = QCheckBox("Create subfolder for playlist")
        self.create_subfolder_chk.setChecked(True)
        playlist_dl_form.addRow("", self.create_subfolder_chk)

        # Download buttons
        playlist_btn_row = QHBoxLayout()
        self.download_playlist_btn = QPushButton("Download Selected", clicked=self._start_playlist_download)
        self.download_playlist_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        playlist_btn_row.addWidget(self.download_playlist_btn)
        playlist_dl_form.addRow(playlist_btn_row)
        
        playlist_dl_grp.setLayout(playlist_dl_form)
        L.addWidget(playlist_dl_grp)

        # Progress section
        playlist_progress_grp = QGroupBox("Progress")
        playlist_progress_layout = QVBoxLayout()
        
        # Overall progress
        playlist_progress_layout.addWidget(QLabel("Overall Progress:"))
        self.playlist_progress_bar = QProgressBar()
        playlist_progress_layout.addWidget(self.playlist_progress_bar)
        
        # Current video progress
        playlist_progress_layout.addWidget(QLabel("Current Video:"))
        self.playlist_current_lbl = QLabel("None")
        playlist_progress_layout.addWidget(self.playlist_current_lbl)
        self.playlist_video_progress_bar = QProgressBar()
        playlist_progress_layout.addWidget(self.playlist_video_progress_bar)
        
        # Log text area
        self.playlist_log_te = QTextEdit()
        self.playlist_log_te.setReadOnly(True)
        self.playlist_log_te.setMinimumHeight(100)
        playlist_progress_layout.addWidget(self.playlist_log_te)
        
        playlist_progress_grp.setLayout(playlist_progress_layout)
        L.addWidget(playlist_progress_grp)

    def _build_batch_tab(self):
        """Build the batch download tab."""
        tab = QWidget()
        self._tabs.addTab(tab, "Batch Download")
        L = QVBoxLayout(tab)

        # URL list
        url_grp = QGroupBox("URLs (one per line)")
        url_layout = QVBoxLayout()
        self.batch_urls_te = QTextEdit()
        url_layout.addWidget(self.batch_urls_te)
        url_grp.setLayout(url_layout)
        L.addWidget(url_grp)

        # Download options
        batch_dl_grp = QGroupBox("Download Options")
        batch_dl_form = QFormLayout()

        self.batch_dl_type_combo = QComboBox()
        self.batch_dl_type_combo.addItems(["Video Download", "Audio Only"])
        batch_dl_form.addRow("Download type:", self.batch_dl_type_combo)

        self.batch_quality_combo = QComboBox()
        self.batch_quality_combo.addItems(["Best", "1080p", "720p", "480p", "360p", "Smallest"])
        batch_dl_form.addRow("Quality:", self.batch_quality_combo)

        # Output directory
        default_output_dir = os.getcwd()  # Use current working directory
        self._settings.setValue("output_dir", default_output_dir)  # Always set the current directory
        self.batch_output_dir_edit = QLineEdit(default_output_dir)
        batch_out_row = QHBoxLayout()
        batch_out_row.addWidget(self.batch_output_dir_edit)
        batch_browse_btn = QPushButton("Browse")
        batch_browse_btn.clicked.connect(lambda: self._browse_output_dir(self.batch_output_dir_edit))
        batch_out_row.addWidget(batch_browse_btn)
        batch_dl_form.addRow("Output directory:", batch_out_row)

        # Download button
        self.download_batch_btn = QPushButton("Start Batch Download", clicked=self._start_batch_download)
        self.download_batch_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        batch_dl_form.addRow(self.download_batch_btn)
        
        batch_dl_grp.setLayout(batch_dl_form)
        L.addWidget(batch_dl_grp)

        # Progress section
        batch_progress_grp = QGroupBox("Progress")
        batch_progress_layout = QVBoxLayout()
        
        # Queue table
        self.batch_queue_table = QTableWidget(0, 4)
        self.batch_queue_table.setHorizontalHeaderLabels(["URL", "Status", "Progress", "Actions"])
        self.batch_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.batch_queue_table.verticalHeader().setDefaultSectionSize(25)  # Reduced row height
        batch_progress_layout.addWidget(self.batch_queue_table)
        
        # Log text area
        self.batch_log_te = QTextEdit()
        self.batch_log_te.setReadOnly(True)
        self.batch_log_te.setFixedHeight(80)  # Reduced height
        batch_progress_layout.addWidget(self.batch_log_te)
        
        batch_progress_grp.setLayout(batch_progress_layout)
        L.addWidget(batch_progress_grp)

    def _build_history_tab(self):
        """Build the download history tab."""
        tab = QWidget()
        self._tabs.addTab(tab, "Download History")
        L = QVBoxLayout(tab)

        # History table
        self.history_tbl = QTableWidget(0, 5)
        self.history_tbl.setHorizontalHeaderLabels(["Date", "Title", "URL", "File Path", "File Size"])
        self.history_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.history_tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        L.addWidget(self.history_tbl)

        # Control buttons
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_history)
        btn_row.addWidget(refresh_btn)
        
        clear_btn = QPushButton("Clear History")
        clear_btn.clicked.connect(self._clear_history)
        btn_row.addWidget(clear_btn)
        
        export_btn = QPushButton("Export History")
        export_btn.clicked.connect(self._export_history)
        btn_row.addWidget(export_btn)
        
        L.addLayout(btn_row)

    def _log(self, msg, error=False):
        """Add a message to the log text area."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "#c5160a"
        formatted_msg = f'<span style="color:{color};">[{timestamp}] {msg}</span>'
        
        # Determine which tab is active and log to the appropriate text edit
        current_tab = self._tabs.tabText(self._tabs.currentIndex())
        if current_tab == "Single Download":
            self.log_te.append(formatted_msg)
        elif current_tab == "Playlist Download":
            self.playlist_log_te.append(formatted_msg)
        elif current_tab == "Batch Download":
            self.batch_log_te.append(formatted_msg)
        
        # Also log to console
        logger.info(msg) if not error else logger.error(msg)
        
        # Update status bar
        self.statusBar().showMessage(msg, 5000)

    def _browse_output_dir(self, line_edit):
        """Open a directory browser dialog and update the specified line edit."""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", line_edit.text()
        )
        if dir_path:
            line_edit.setText(dir_path)

    def _toggle_trim_enabled(self, checked):
        """Enable or disable trimming controls based on checkbox state."""
        self.trim_start_edit.setEnabled(checked)
        self.trim_end_edit.setEnabled(checked)
        
        # If enabling and duration is known, set end time to video duration
        if checked and self._video_info and self._video_info.get("duration"):
            duration = int(self._video_info.get("duration", 0))
            if duration > 0 and not self.trim_end_edit.text():
                self.trim_end_edit.setText(seconds_to_hhmmss(duration))

    def _open_settings_dialog(self):
        """Open the settings dialog."""
        dialog = SettingsDialog(self)
        if dialog.exec():
            # Update settings that might affect the current session
            self._max_concurrent_downloads = int(self._settings.value("max_concurrent_downloads", "2"))
            self._log("Settings updated")

    def _export_logs(self):
        """Export logs to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Logs", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    # Get logs from all tabs
                    f.write("=== Single Download Logs ===\n")
                    f.write(self.log_te.toPlainText())
                    f.write("\n\n=== Playlist Download Logs ===\n")
                    f.write(self.playlist_log_te.toPlainText())
                    f.write("\n\n=== Batch Download Logs ===\n")
                    f.write(self.batch_log_te.toPlainText())
                self._log(f"Logs exported to {file_path}")
            except Exception as e:
                self._log(f"Failed to export logs: {str(e)}", error=True)

    def _show_about(self):
        """Show the about dialog."""
        about_text = """
        <h2 style='color:#c5160a;'>YTGrabber</h2>
        <p>Version 1.0.0</p>
        <p>A powerful YouTube video downloader with advanced features.</p>
        <p>by Ibrahim Hammad (HaMMaDy)</p>
        <p>GitHub: <a href='https://github.com/xHaMMaDy'>@xHaMMaDy</a></p>
        <p>Features:</p>
        <ul>
            <li>Download videos in various formats and qualities</li>
            <li>Download audio only</li>
            <li>Trim videos</li>
            <li>Download playlists</li>
            <li>Batch download</li>
            <li>Download history tracking</li>
        </ul>
        """
        
        dialog = QDialog(self)
        dialog.setWindowTitle("About YTGrabber")
        layout = QVBoxLayout(dialog)
        
        text_label = QLabel(about_text)
        text_label.setOpenExternalLinks(True)
        layout.addWidget(text_label)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()

    # ------------------------------------------------------------------
    # Fetch info flow
    # ------------------------------------------------------------------
    
    def _fetch_info(self):
        """Fetch information about a single video."""
        url = self.url_edit.text().strip()
        if not is_valid_youtube_link(url):
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Check if it's a playlist
        if is_youtube_playlist(url):
            # Ask if user wants to switch to playlist tab
            reply = QMessageBox.question(
                self,
                "Playlist Detected",
                "This appears to be a playlist URL. Would you like to switch to the Playlist tab?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.playlist_url_edit.setText(url)
                self._tabs.setCurrentIndex(1)  # Switch to playlist tab
                self._fetch_playlist_info()
                return
        
        self._log("Fetching video info...")
        self.fetch_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        
        # Clear previous info
        self._video_info = None
        self.title_lbl.setText("N/A")
        self.channel_lbl.setText("N/A")
        self.duration_lbl.setText("N/A")
        self.upload_lbl.setText("N/A")
        self.thumb_label.setPixmap(QPixmap())
        self.fmt_combo.clear()
        
        # Create and start worker
        worker = FetchInfoWorker(url)
        worker.progress.connect(self._log)
        worker.finished.connect(self._on_info_fetched)
        worker.error.connect(lambda e: self._log(e, error=True))
        worker.finished.connect(lambda _: self.fetch_btn.setEnabled(True))
        
        self._workers.append(worker)
        worker.start()

    def _on_info_fetched(self, info):
        """Handle fetched video information."""
        self._video_info = info
        
        # Update UI with video info
        self.title_lbl.setText(info.get("title", "N/A"))
        self.channel_lbl.setText(info.get("uploader", "N/A"))
        self.duration_lbl.setText(format_duration(info.get("duration", "N/A")))
        
        # Format upload date
        up = info.get("upload_date", "N/A")
        if isinstance(up, str) and len(up) == 8:
            up = f"{up[:4]}-{up[4:6]}-{up[6:]}"
        self.upload_lbl.setText(up)
        
        # Load highest quality thumbnail
        thumbnails = info.get("thumbnails", [])
        if thumbnails:
            # Sort thumbnails by resolution (width * height) to get highest quality
            thumbnails.sort(key=lambda x: (x.get("width", 0) * x.get("height", 0)), reverse=True)
            best_thumb = thumbnails[0].get("url")
            if best_thumb:
                pix = download_image_as_pixmap(best_thumb)
                if not pix.isNull():
                    # Scale with better quality and smoother transformation
                    scaled_pix = pix.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.thumb_label.setPixmap(scaled_pix)
                    # Enable mouse tracking for hover effect
                    self.thumb_label.setMouseTracking(True)
                    # Store original pixmap for preview
                    self.thumb_label.setProperty("original_pixmap", pix)
        
        # Update format combo box
        self._update_format_combo()
        
        # Check if auto-trim should be enabled for long videos
        if self._settings.value("auto_trim", "false") == "true":
            duration = int(info.get("duration", 0))
            if duration > 30 * 60:  # 30 minutes
                self.trim_chk.setChecked(True)
        
        self._log("Video info fetched successfully")

    def _update_format_combo(self):
        """Update the format combo box with available formats."""
        self.fmt_combo.clear()
        if not self._video_info:
            return
        
        dl_type = self.dl_type_combo.currentText()
        fmts = self._video_info.get("formats", [])
        duration = int(self._video_info.get("duration", 0))
        
        if dl_type == "Video Download":
            # Filter and sort video formats
            vids = [f for f in fmts if f.get("vcodec") not in (None, "none")]
            vids.sort(key=lambda f: (f.get("height", 0), f.get("tbr", 0)), reverse=True)
            
            # Add formats to combo box
            for f in vids:
                height = f.get("height", "?")
                ext = f.get("ext", "?")
                fid = f["format_id"]
                br = total_bitrate_mbps(f)
                size = size_bytes(f, duration)
                br_txt = f"{br:.1f} Mbps" if br else "? Mbps"
                size_txt = f"~{human_mb(size)}" if size else "—"
                label = f"{height}p | {ext} | {br_txt} | {size_txt}"
                # Store both format_id and ext in the user data
                self.fmt_combo.addItem(label, {"id": fid, "ext": ext})
        else:
            # Filter and sort audio formats
            auds = [f for f in fmts if f.get("acodec") not in (None, "none")]
            auds.sort(key=lambda f: f.get("abr", 0), reverse=True)
            
            # Add formats to combo box
            for f in auds:
                abr = f.get("abr", "?")
                ext = f.get("ext", "?")
                fid = f["format_id"]
                size = size_bytes(f, duration)
                size_txt = f"~{human_mb(size)}" if size else "—"
                label = f"{abr}kbps | {ext} | {size_txt}"
                # Store both format_id and ext in the user data
                self.fmt_combo.addItem(label, {"id": fid, "ext": ext})
        
        # Add a placeholder if no formats found
        if self.fmt_combo.count() == 0:
            self.fmt_combo.addItem("No formats", {"id": "", "ext": ""})

    def _preview_thumb(self):
        """Show a larger preview of the thumbnail."""
        original_pix = self.thumb_label.property("original_pixmap")
        if original_pix:
            dlg = QDialog(self)
            dlg.setWindowTitle("Thumbnail Preview")
            dlg.setStyleSheet("background-color: #202124;")  # Match app theme
            layout = QVBoxLayout(dlg)
            
            # Create preview label
            label = QLabel()
            # Scale to a larger size while maintaining aspect ratio and quality
            preview_size = QSize(854, 480)  # 16:9 aspect ratio, larger size
            scaled_pix = original_pix.scaled(preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled_pix)
            label.setAlignment(Qt.AlignCenter)
            
            # Add a subtle border
            label.setStyleSheet("border: 2px solid #c5160a; border-radius: 5px; padding: 5px;")
            
            layout.addWidget(label)
            
            # Close button with styling
            close_btn = QPushButton("Close")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #c5160a;
                    color: white;
                    border: none;
                    padding: 5px 15px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #a01208;
                }
                QPushButton:pressed {
                    background-color: #800e06;
                }
            """)
            close_btn.clicked.connect(dlg.accept)
            layout.addWidget(close_btn, alignment=Qt.AlignCenter)
            
            # Set dialog size with margins
            layout.setContentsMargins(20, 20, 20, 20)
            dlg.exec()

    # ------------------------------------------------------------------
    # Playlist functions
    # ------------------------------------------------------------------
    
    def _fetch_playlist_info(self):
        """Fetch information about a playlist."""
        url = self.playlist_url_edit.text().strip()
        if not is_youtube_playlist(url):
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid YouTube playlist URL.")
            return
        
        self._log("Fetching playlist info...")
        self.fetch_playlist_btn.setEnabled(False)
        self.playlist_progress_bar.setValue(0)
        
        # Clear previous info
        self._playlist_info = None
        self.playlist_title_lbl.setText("N/A")
        self.playlist_count_lbl.setText("N/A")
        self.playlist_table.setRowCount(0)
        
        # Create and start worker
        worker = FetchPlaylistInfoWorker(url)
        worker.progress.connect(self._log)
        worker.finished.connect(self._on_playlist_info_fetched)
        worker.error.connect(lambda e: self._log(e, error=True))
        worker.finished.connect(lambda _: self.fetch_playlist_btn.setEnabled(True))
        
        self._workers.append(worker)
        worker.start()

    def _on_playlist_info_fetched(self, videos):
        """Handle fetched playlist information."""
        if not videos:
            self._log("No videos found in playlist", error=True)
            return
        
        self._playlist_info = videos
        
        # Update playlist info
        first_video = videos[0]
        playlist_title = first_video.get("playlist_title", "Unknown Playlist")
        self.playlist_title_lbl.setText(playlist_title)
        self.playlist_count_lbl.setText(str(len(videos)))
        
        # Populate table
        self.playlist_table.setRowCount(len(videos))
        for i, video in enumerate(videos):
            # Title
            title_item = QTableWidgetItem(video.get("title", "Unknown"))
            title_item.setFlags(title_item.flags() & ~Qt.ItemIsEditable)
            self.playlist_table.setItem(i, 0, title_item)
            
            # Duration
            duration = video.get("duration")
            duration_text = seconds_to_hhmmss(duration) if duration else "Unknown"
            duration_item = QTableWidgetItem(duration_text)
            duration_item.setFlags(duration_item.flags() & ~Qt.ItemIsEditable)
            self.playlist_table.setItem(i, 1, duration_item)
            
            # Status
            status_item = QTableWidgetItem("Pending")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.playlist_table.setItem(i, 2, status_item)
            
            # Checkbox for selection
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.playlist_table.setCellWidget(i, 3, checkbox)
        
        self._log(f"Playlist info fetched successfully: {len(videos)} videos")

    def _select_all_playlist_videos(self):
        """Select all videos in the playlist."""
        for i in range(self.playlist_table.rowCount()):
            checkbox = self.playlist_table.cellWidget(i, 3)
            if checkbox:
                checkbox.setChecked(True)

    def _deselect_all_playlist_videos(self):
        """Deselect all videos in the playlist."""
        for i in range(self.playlist_table.rowCount()):
            checkbox = self.playlist_table.cellWidget(i, 3)
            if checkbox:
                checkbox.setChecked(False)

    def _invert_playlist_selection(self):
        """Invert the selection of videos in the playlist."""
        for i in range(self.playlist_table.rowCount()):
            checkbox = self.playlist_table.cellWidget(i, 3)
            if checkbox:
                checkbox.setChecked(not checkbox.isChecked())

    def _start_playlist_download(self):
        """Start downloading selected videos from the playlist."""
        if not self._playlist_info:
            QMessageBox.warning(self, "No Playlist", "Please fetch playlist info first.")
            return
        
        # Get selected videos
        selected_indices = []
        for i in range(self.playlist_table.rowCount()):
            checkbox = self.playlist_table.cellWidget(i, 3)
            if checkbox and checkbox.isChecked():
                selected_indices.append(i)
        
        if not selected_indices:
            QMessageBox.warning(self, "No Selection", "Please select at least one video to download.")
            return
        
        # Get download options
        dl_type = self.playlist_dl_type_combo.currentText()
        quality = self.playlist_quality_combo.currentText()
        output_dir = self.playlist_output_dir_edit.text()
        create_subfolder = self.create_subfolder_chk.isChecked()
        
        # Create subfolder if needed
        if create_subfolder:
            playlist_title = self.playlist_title_lbl.text()
            playlist_dir = os.path.join(output_dir, sanitize_filename(playlist_title))
            os.makedirs(playlist_dir, exist_ok=True)
            output_dir = playlist_dir
        
        # Prepare download queue
        for idx in selected_indices:
            video = self._playlist_info[idx]
            video_url = f"https://www.youtube.com/watch?v={video.get('id')}"
            
            # Create download item
            download_item = {
                "url": video_url,
                "title": video.get("title", "Unknown"),
                "output_dir": output_dir,
                "dl_type": dl_type,
                "quality": quality,
                "playlist_index": idx
            }
            
            # Add to queue
            self._download_queue.append(download_item)
            
            # Update status in table
            status_item = QTableWidgetItem("Queued")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.playlist_table.setItem(idx, 2, status_item)
        
        self._log(f"Added {len(selected_indices)} videos to download queue")
        self.playlist_progress_bar.setValue(0)
        self.playlist_progress_bar.setMaximum(len(selected_indices))
        
        # Start processing queue
        self._process_download_queue()

    # ------------------------------------------------------------------
    # Batch download functions
    # ------------------------------------------------------------------
    
    def _start_batch_download(self):
        """Start batch download of URLs."""
        urls = self.batch_urls_te.toPlainText().strip().split("\n")
        urls = [url.strip() for url in urls if url.strip()]
        
        if not urls:
            QMessageBox.warning(self, "No URLs", "Please enter at least one URL.")
            return
        
        # Get download options
        dl_type = self.batch_dl_type_combo.currentText()
        quality = self.batch_quality_combo.currentText()
        output_dir = self.batch_output_dir_edit.text()
        
        # Clear queue table
        self.batch_queue_table.setRowCount(len(urls))
        
        # Add URLs to queue
        for i, url in enumerate(urls):
            # Add URL to table
            url_item = QTableWidgetItem(url)
            url_item.setFlags(url_item.flags() & ~Qt.ItemIsEditable)
            self.batch_queue_table.setItem(i, 0, url_item)
            
            # Set status
            status_item = QTableWidgetItem("Queued")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.batch_queue_table.setItem(i, 1, status_item)
            
            # Add progress bar
            progress_bar = QProgressBar()
            progress_bar.setValue(0)
            self.batch_queue_table.setCellWidget(i, 2, progress_bar)
            
            # Add cancel button
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setProperty("url_index", i)
            cancel_btn.clicked.connect(self._cancel_batch_item)
            self.batch_queue_table.setCellWidget(i, 3, cancel_btn)
            
            # Create download item
            download_item = {
                "url": url,
                "output_dir": output_dir,
                "dl_type": dl_type,
                "quality": quality,
                "batch_index": i
            }
            
            # Add to queue
            self._download_queue.append(download_item)
        
        self._log(f"Added {len(urls)} URLs to download queue")
        
        # Start processing queue
        self._process_download_queue()

    def _cancel_batch_item(self):
        """Cancel a batch download item."""
        sender = self.sender()
        if not sender:
            return
        
        idx = sender.property("url_index")
        if idx is None:
            return
        
        # Find item in queue
        for i, item in enumerate(self._download_queue):
            if item.get("batch_index") == idx:
                # Remove from queue
                self._download_queue.pop(i)
                
                # Update status in table
                status_item = QTableWidgetItem("Cancelled")
                status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
                self.batch_queue_table.setItem(idx, 1, status_item)
                
                # Disable cancel button
                self.batch_queue_table.cellWidget(idx, 3).setEnabled(False)
                
                self._log(f"Cancelled download of {item.get('url')}")
                break

    # ------------------------------------------------------------------
    # Download functions
    # ------------------------------------------------------------------
    
    def _start_download(self):
        """Start downloading a single video."""
        if not self._video_info:
            QMessageBox.warning(self, "No Video", "Please fetch video info first.")
            return
        
        url = self.url_edit.text().strip()
        fmt_data = self.fmt_combo.currentData()
        
        if not fmt_data or not fmt_data.get("id"):
            QMessageBox.warning(self, "No Format", "Please select a format.")
            return
        
        fmt_id = fmt_data.get("id")
        dl_type = self.dl_type_combo.currentText()
        is_audio_only = (dl_type == "Audio Only")
        
        # Get output filename
        quality_text = self.fmt_combo.currentText().split(" | ")[0]
        ext = ".mp3" if is_audio_only else ".mp4"
        title_safe = sanitize_filename(self._video_info.get("title", "untitled"))
        
        # Check if trimming is enabled and add trim info to filename
        trim_enabled = self.trim_chk.isChecked()
        if trim_enabled:
            start_time = self.trim_start_edit.text().strip() or "00:00:00"
            end_time = self.trim_end_edit.text().strip()
            if not end_time and self._video_info.get("duration"):
                end_time = seconds_to_hhmmss(int(self._video_info.get("duration", 0)))
            # Add trim info to filename
            out_name = f"{title_safe}_{quality_text}_trimmed_{start_time.replace(':', '')}_{end_time.replace(':', '')}{ext}"
        else:
            out_name = f"{title_safe}_{quality_text}{ext}"
        
        out_path = os.path.join(self.output_dir_edit.text(), out_name)
        
        # Check if file exists
        if os.path.exists(out_path):
            reply = QMessageBox.question(
                self,
                "File Exists",
                f"The file '{out_name}' already exists. Do you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # Disable download button and enable pause button
        self.download_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        
        # Reset progress
        self.progress_bar.setValue(0)
        self.speed_lbl.setText("Speed: --")
        self.eta_lbl.setText("ETA: --")
        
        if trim_enabled:
            # Get trim times
            start_time = self.trim_start_edit.text().strip() or "00:00:00"
            end_time = self.trim_end_edit.text().strip()
            if not end_time and self._video_info.get("duration"):
                end_time = seconds_to_hhmmss(int(self._video_info.get("duration", 0)))
            
            self._log(f"Starting trimmed download from {start_time} to {end_time}")
            
            # Create and start trim worker
            worker = TrimWorker(url, out_path, start_time, end_time)
            worker.progress.connect(self.progress_bar.setValue)
            worker.progress_text.connect(self._log)
            worker.finished.connect(self._on_download_finished)
            worker.error.connect(lambda e: self._log(e, error=True))
            
            self._current_worker = worker
            self._workers.append(worker)
            worker.start()
        else:
            self._log("Starting download")
            
            # Create extra options for download
            extra_options = {
                "format": fmt_id if is_audio_only else f"{fmt_id}+bestaudio/best",
                "merge-output-format": "mp4"
            }
            
            if is_audio_only:
                extra_options["extract-audio"] = True
                extra_options["audio-format"] = "mp3"
            
            # Add fallback formats
            if not is_audio_only:
                extra_options["format"] = f"{fmt_id}+bestaudio/best/bestvideo+bestaudio"
            
            # Create and start download worker
            worker = DownloadWorker(
                url, out_path, None, extra_options, self._settings, is_audio_only
            )
            worker.progress.connect(self.progress_bar.setValue)
            worker.progress_text.connect(self._log)
            worker.finished.connect(self._on_download_finished)
            worker.error.connect(lambda e: self._log(e, error=True))
            worker.paused.connect(lambda p: self.pause_btn.setText("Resume" if p else "Pause"))
            worker.speed_update.connect(self._update_speed_info)
            
            self._current_worker = worker
            self._workers.append(worker)
            worker.start()

    def _update_speed_info(self, bytes_per_sec, eta_seconds):
        """Update speed and ETA information."""
        self.speed_lbl.setText(f"Speed: {format_speed(bytes_per_sec)}")
        self.eta_lbl.setText(f"ETA: {seconds_to_hhmmss(eta_seconds)}")

    def _toggle_pause(self):
        """Toggle pause/resume of the current download."""
        if self._current_worker:
            if hasattr(self._current_worker, "toggle_pause"):
                self._current_worker.toggle_pause()
                is_paused = getattr(self._current_worker, "_paused", False)
                self.pause_btn.setText("Resume" if is_paused else "Pause")
                self._log(f"Download {'paused' if is_paused else 'resumed'}")

    def _on_download_finished(self, filepath, filesize):
        """Handle download completion."""
        self.download_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self._current_worker = None
        
        if os.path.exists(filepath):
            self._log(f"Download completed: {filepath} ({format_filesize(filesize)})")
            
            # Add to history
            if self._video_info:
                append_download_history(
                    self._video_info.get("title", "Unknown"),
                    self.url_edit.text().strip(),
                    filepath,
                    filesize
                )
            
            # Show success message
            QMessageBox.information(
                self,
                "Download Complete",
                f"Download completed successfully!\n\nFile: {os.path.basename(filepath)}\nSize: {format_filesize(filesize)}"
            )
        else:
            self._log("Download failed: File not found", error=True)

    def _process_download_queue(self):
        """Process the download queue."""
        # Check if we can start more downloads
        if self._active_downloads >= self._max_concurrent_downloads:
            return
        
        # Check if there are items in the queue
        if not self._download_queue:
            return
        
        # Get next item from queue
        item = self._download_queue[0]
        self._download_queue.pop(0)
        
        # Increment active downloads counter
        self._active_downloads += 1
        
        # Start download based on item type
        if "playlist_index" in item:
            self._start_playlist_item_download(item)
        elif "batch_index" in item:
            self._start_batch_item_download(item)
        else:
            # Decrement counter if item type is unknown
            self._active_downloads -= 1

    def _start_playlist_item_download(self, item):
        """Start downloading a playlist item."""
        idx = item["playlist_index"]
        url = item["url"]
        output_dir = item["output_dir"]
        dl_type = item["dl_type"]
        quality = item["quality"]
        is_audio_only = (dl_type == "Audio Only")
        
        # Update status in table
        status_item = QTableWidgetItem("Downloading")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.playlist_table.setItem(idx, 2, status_item)
        
        # Update current video label
        self.playlist_current_lbl.setText(item["title"])
        
        # Determine format based on quality
        format_option = ""
        if is_audio_only:
            format_option = "bestaudio"
        else:
            if quality == "Best":
                format_option = "bestvideo+bestaudio"
            elif quality == "1080p":
                format_option = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            elif quality == "720p":
                format_option = "bestvideo[height<=720]+bestaudio/best[height<=720]"
            elif quality == "480p":
                format_option = "bestvideo[height<=480]+bestaudio/best[height<=480]"
            elif quality == "360p":
                format_option = "bestvideo[height<=360]+bestaudio/best[height<=360]"
            elif quality == "Smallest":
                format_option = "worstvideo+worstaudio/worst"
        
        # Determine output filename
        title_safe = sanitize_filename(item["title"])
        ext = ".mp3" if is_audio_only else ".mp4"
        out_name = f"{title_safe}{ext}"
        out_path = os.path.join(output_dir, out_name)
        
        # Create extra options
        extra_options = {}
        if is_audio_only:
            extra_options["extract-audio"] = True
            extra_options["audio-format"] = "mp3"
        
        # Log start
        self._log(f"Starting download of playlist item: {item['title']}")
        
        # Create and start worker
        worker = DownloadWorker(
            url, out_path, format_option, extra_options, self._settings, is_audio_only
        )
        
        # Connect signals
        worker.progress.connect(self.playlist_video_progress_bar.setValue)
        worker.progress_text.connect(self._log)
        worker.finished.connect(lambda fp, fs: self._on_playlist_item_finished(fp, fs, idx))
        worker.error.connect(lambda e: self._on_playlist_item_error(e, idx))
        
        # Start worker
        self._workers.append(worker)
        worker.start()

    def _on_playlist_item_finished(self, filepath, filesize, idx):
        """Handle playlist item download completion."""
        # Update status in table
        status_item = QTableWidgetItem("Completed")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.playlist_table.setItem(idx, 2, status_item)
        
        # Log completion
        self._log(f"Playlist item completed: {os.path.basename(filepath)} ({format_filesize(filesize)})")
        
        # Add to history
        if idx < len(self._playlist_info):
            video = self._playlist_info[idx]
            append_download_history(
                video.get("title", "Unknown"),
                f"https://www.youtube.com/watch?v={video.get('id')}",
                filepath,
                filesize
            )
        
        # Update progress bar
        completed = sum(1 for i in range(self.playlist_table.rowCount()) 
                      if self.playlist_table.item(i, 2) and 
                      self.playlist_table.item(i, 2).text() == "Completed")
        self.playlist_progress_bar.setValue(completed)
        
        # Decrement active downloads counter
        self._active_downloads -= 1
        
        # Process next item in queue
        self._process_download_queue()

    def _on_playlist_item_error(self, error_msg, idx):
        """Handle playlist item download error."""
        # Update status in table
        status_item = QTableWidgetItem("Failed")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.playlist_table.setItem(idx, 2, status_item)
        
        # Log error
        self._log(f"Playlist item failed: {error_msg}", error=True)
        
        # Decrement active downloads counter
        self._active_downloads -= 1
        
        # Process next item in queue
        self._process_download_queue()

    def _start_batch_item_download(self, item):
        """Start downloading a batch item."""
        idx = item["batch_index"]
        url = item["url"]
        output_dir = item["output_dir"]
        dl_type = item["dl_type"]
        quality = item["quality"]
        is_audio_only = (dl_type == "Audio Only")
        
        # Update status in table
        status_item = QTableWidgetItem("Downloading")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.batch_queue_table.setItem(idx, 1, status_item)
        
        # Determine format based on quality
        format_option = ""
        if is_audio_only:
            format_option = "bestaudio"
        else:
            if quality == "Best":
                format_option = "bestvideo+bestaudio"
            elif quality == "1080p":
                format_option = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            elif quality == "720p":
                format_option = "bestvideo[height<=720]+bestaudio/best[height<=720]"
            elif quality == "480p":
                format_option = "bestvideo[height<=480]+bestaudio/best[height<=480]"
            elif quality == "360p":
                format_option = "bestvideo[height<=360]+bestaudio/best[height<=360]"
            elif quality == "Smallest":
                format_option = "worstvideo+worstaudio/worst"
        
        # Create temporary filename for initial download
        temp_filename = f"temp_{int(time.time())}_{idx}"
        ext = ".mp3" if is_audio_only else ".mp4"
        temp_path = os.path.join(output_dir, temp_filename + ext)
        
        # Create extra options
        extra_options = {
            "output-na-placeholder": "unknown"
        }
        if is_audio_only:
            extra_options["extract-audio"] = True
            extra_options["audio-format"] = "mp3"
        
        # Log start
        self._log(f"Starting download of batch item: {url}")
        
        # Create and start worker
        worker = DownloadWorker(
            url, temp_path, format_option, extra_options, self._settings, is_audio_only
        )
        
        # Connect signals
        progress_bar = self.batch_queue_table.cellWidget(idx, 2)
        if progress_bar:
            worker.progress.connect(progress_bar.setValue)
        
        worker.progress_text.connect(self._log)
        worker.finished.connect(lambda fp, fs: self._on_batch_item_finished(fp, fs, idx, url))
        worker.error.connect(lambda e: self._on_batch_item_error(e, idx))
        
        # Start worker
        self._workers.append(worker)
        worker.start()

    def _on_batch_item_finished(self, filepath, filesize, idx, url):
        """Handle batch item download completion."""
        # Update status in table
        status_item = QTableWidgetItem("Completed")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.batch_queue_table.setItem(idx, 1, status_item)
        
        # Disable cancel button
        cancel_btn = self.batch_queue_table.cellWidget(idx, 3)
        if cancel_btn:
            cancel_btn.setEnabled(False)
        
        # Rename file to include video title
        try:
            # Get video info to determine proper filename
            result = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-playlist", url],
                capture_output=True, 
                text=True, 
                check=True,
                startupinfo=get_startupinfo()
            )
            
            info = json.loads(result.stdout)
            title = info.get("title", "unknown")
            title_safe = sanitize_filename(title)
            
            # Determine new filename
            ext = os.path.splitext(filepath)[1]
            output_dir = os.path.dirname(filepath)
            new_filepath = os.path.join(output_dir, f"{title_safe}{ext}")
            
            # Rename file
            if os.path.exists(filepath):
                if os.path.exists(new_filepath):
                    # Add number suffix if file already exists
                    base, ext = os.path.splitext(new_filepath)
                    i = 1
                    while os.path.exists(f"{base}_{i}{ext}"):
                        i += 1
                    new_filepath = f"{base}_{i}{ext}"
                
                os.rename(filepath, new_filepath)
                filepath = new_filepath
        except Exception as e:
            self._log(f"Error renaming file: {str(e)}", error=True)
        
        # Log completion
        self._log(f"Batch item completed: {os.path.basename(filepath)} ({format_filesize(filesize)})")
        
        # Add to history
        append_download_history(
            os.path.splitext(os.path.basename(filepath))[0],
            url,
            filepath,
            filesize
        )
        
        # Decrement active downloads counter
        self._active_downloads -= 1
        
        # Process next item in queue
        self._process_download_queue()

    def _on_batch_item_error(self, error_msg, idx):
        """Handle batch item download error."""
        # Update status in table
        status_item = QTableWidgetItem("Failed")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.batch_queue_table.setItem(idx, 1, status_item)
        
        # Disable cancel button
        cancel_btn = self.batch_queue_table.cellWidget(idx, 3)
        if cancel_btn:
            cancel_btn.setEnabled(False)
        
        # Log error
        self._log(f"Batch item failed: {error_msg}", error=True)
        
        # Decrement active downloads counter
        self._active_downloads -= 1
        
        # Process next item in queue
        self._process_download_queue()

    # ------------------------------------------------------------------
    # History functions
    # ------------------------------------------------------------------
    
    def _load_history(self):
        """Load download history from CSV file."""
        try:
            self.history_tbl.setRowCount(0)
            
            if not os.path.exists("download_history.csv"):
                return
            
            with open("download_history.csv", "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            
            self.history_tbl.setRowCount(len(rows))
            
            for i, row in enumerate(rows):
                for j, cell in enumerate(row):
                    item = QTableWidgetItem(cell)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.history_tbl.setItem(i, j, item)
            
            self._log(f"Loaded {len(rows)} history entries")
            
        except Exception as e:
            self._log(f"Error loading history: {str(e)}", error=True)

    def _clear_history(self):
        """Clear download history."""
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all download history?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            if os.path.exists("download_history.csv"):
                os.remove("download_history.csv")
            
            self.history_tbl.setRowCount(0)
            self._log("Download history cleared")
            
        except Exception as e:
            self._log(f"Error clearing history: {str(e)}", error=True)

    def _export_history(self):
        """Export download history to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export History", "", "CSV Files (*.csv);;All Files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if os.path.exists("download_history.csv"):
                import shutil
                shutil.copy2("download_history.csv", file_path)
                self._log(f"History exported to {file_path}")
            else:
                self._log("No history to export", error=True)
                
        except Exception as e:
            self._log(f"Error exporting history: {str(e)}", error=True)

    def _open_download_settings(self):
        """Open download settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Download Settings")
        layout = QFormLayout(dialog)
        
        # Max concurrent downloads
        max_downloads = QSpinBox()
        max_downloads.setRange(1, 10)
        max_downloads.setValue(int(self._settings.value("max_concurrent_downloads", "2")))
        layout.addRow("Max concurrent downloads:", max_downloads)
        
        # Download rate limit
        rate_limit = QLineEdit(self._settings.value("limit_rate", ""))
        rate_limit.setPlaceholderText("e.g., 1M, 500K (leave blank for no limit)")
        layout.addRow("Download rate limit:", rate_limit)
        
        # Retry attempts
        retries = QSpinBox()
        retries.setRange(0, 10)
        retries.setValue(int(self._settings.value("retries", "3")))
        layout.addRow("Retry attempts:", retries)
        
        # Auto-enable trimming
        auto_trim = QCheckBox("Auto-enable trimming for long videos (>30 min)")
        auto_trim.setChecked(self._settings.value("auto_trim", "false") == "true")
        layout.addRow("", auto_trim)
        
        # Buttons
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_download_settings(
            max_downloads.value(), rate_limit.text(), retries.value(), auto_trim.isChecked(), dialog
        ))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow("", btn_box)
        
        dialog.exec()

    def _save_download_settings(self, max_downloads, rate_limit, retries, auto_trim, dialog):
        """Save download settings."""
        self._settings.setValue("max_concurrent_downloads", str(max_downloads))
        self._settings.setValue("limit_rate", rate_limit)
        self._settings.setValue("retries", str(retries))
        self._settings.setValue("auto_trim", "true" if auto_trim else "false")
        self._max_concurrent_downloads = max_downloads
        dialog.accept()
        self._log("Download settings updated")

    def _open_network_settings(self):
        """Open network settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Network Settings")
        layout = QFormLayout(dialog)
        
        # Proxy settings
        proxy = QLineEdit(self._settings.value("proxy", ""))
        proxy.setPlaceholderText("http://user:pass@host:port")
        layout.addRow("Proxy:", proxy)
        
        # Cookies file
        cookies_row = QHBoxLayout()
        cookies_file = QLineEdit(self._settings.value("cookies_file", ""))
        cookies_row.addWidget(cookies_file)
        cookies_browse = QPushButton("Browse")
        cookies_browse.clicked.connect(lambda: self._browse_cookies_file(cookies_file))
        cookies_row.addWidget(cookies_browse)
        layout.addRow("Cookies file:", cookies_row)
        
        # Network timeout
        timeout = QSpinBox()
        timeout.setRange(5, 300)
        timeout.setValue(int(self._settings.value("timeout", "10")))
        timeout.setSuffix(" seconds")
        layout.addRow("Network timeout:", timeout)
        
        # Geo bypass
        geo_bypass = QCheckBox("Enable geo-restriction bypass")
        geo_bypass.setChecked(self._settings.value("geo_bypass", "false") == "true")
        layout.addRow("", geo_bypass)
        
        # Buttons
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_network_settings(
            proxy.text(), cookies_file.text(), timeout.value(), geo_bypass.isChecked(), dialog
        ))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow("", btn_box)
        
        dialog.exec()

    def _save_network_settings(self, proxy, cookies_file, timeout, geo_bypass, dialog):
        """Save network settings."""
        self._settings.setValue("proxy", proxy)
        self._settings.setValue("cookies_file", cookies_file)
        self._settings.setValue("timeout", str(timeout))
        self._settings.setValue("geo_bypass", "true" if geo_bypass else "false")
        dialog.accept()
        self._log("Network settings updated")

    def _open_ui_settings(self):
        """Open UI settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("UI Settings")
        layout = QFormLayout(dialog)
        
        # Theme selection
        theme = QComboBox()
        theme.addItems(["Dark", "Light"])
        current_theme = self._settings.value("theme", "Dark")
        theme.setCurrentText(current_theme)
        layout.addRow("Theme:", theme)
        
        # Font size
        font_size = QSpinBox()
        font_size.setRange(8, 24)
        font_size.setValue(int(self._settings.value("font_size", "10")))
        layout.addRow("Font size:", font_size)
        
        # Show thumbnails
        show_thumbs = QCheckBox("Show video thumbnails")
        show_thumbs.setChecked(self._settings.value("show_thumbnails", "true") == "true")
        layout.addRow("", show_thumbs)
        
        # Buttons
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_ui_settings(
            theme.currentText(), font_size.value(), show_thumbs.isChecked(), dialog
        ))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow("", btn_box)
        
        dialog.exec()

    def _save_ui_settings(self, theme, font_size, show_thumbs, dialog):
        """Save UI settings."""
        self._settings.setValue("theme", theme)
        self._settings.setValue("font_size", str(font_size))
        self._settings.setValue("show_thumbnails", "true" if show_thumbs else "false")
        dialog.accept()
        QMessageBox.information(self, "Settings Updated", 
                              "UI settings have been updated. Please restart the application for changes to take effect.")
        self._log("UI settings updated")

    def _check_updates(self):
        """Check for application updates."""
        QMessageBox.information(self, "Check for Updates",
                              "You are running the latest version (v1.0.0)")

    def _browse_cookies_file(self, line_edit):
        """Browse for cookies file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Cookies File", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            line_edit.setText(file_path)

    def _save_thumbnail(self):
        """Save the current thumbnail to disk."""
        if not hasattr(self.thumb_label, "property") or not self.thumb_label.property("original_pixmap"):
            QMessageBox.warning(self, "No Thumbnail", "No thumbnail available to save.")
            return
        
        if not self._video_info:
            QMessageBox.warning(self, "No Video Info", "No video information available.")
            return
        
        # Get the original high-quality pixmap
        original_pix = self.thumb_label.property("original_pixmap")
        
        # Create default filename from video title
        video_title = self._video_info.get("title", "thumbnail")
        safe_title = sanitize_filename(video_title)
        default_filename = f"{safe_title}_thumbnail.jpg"
        
        # Open file dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Thumbnail",
            os.path.join(self.output_dir_edit.text(), default_filename),
            "Images (*.jpg *.jpeg *.png);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # Save the image
                if original_pix.save(file_path):
                    self._log(f"Thumbnail saved successfully to: {file_path}")
                    
                    # Show success message with option to open folder
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Thumbnail Saved")
                    msg.setText("Thumbnail saved successfully!")
                    msg.setInformativeText(f"Saved to: {file_path}")
                    open_folder_btn = msg.addButton("Open Folder", QMessageBox.ActionRole)
                    msg.addButton(QMessageBox.Close)
                    
                    msg.exec()
                    
                    # Handle open folder button click
                    if msg.clickedButton() == open_folder_btn:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(file_path)))
                else:
                    raise Exception("Failed to save image")
                    
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to save thumbnail: {str(e)}"
                )
                self._log(f"Error saving thumbnail: {str(e)}", error=True)

    def _toggle_theme(self):
        """Toggle between light and dark themes."""
        current_theme = self._settings.value("theme", "dark")
        new_theme = "light" if current_theme == "dark" else "dark"
        self._settings.setValue("theme", new_theme)
        self._apply_theme()
        
        # Update title bar elements
        self._title_bar._update_theme_button()
        
        # Update all menus in the title bar
        for menu in self.findChildren(QMenu):
            self._title_bar._update_menu_style(menu)

    def _apply_theme(self):
        """Apply the current theme to the application."""
        is_dark = self._settings.value("theme", "dark") == "dark"
        
        if is_dark:
            theme = qdarktheme.load_stylesheet("dark")
            bg_color = "#202124"
            secondary_bg = "#2a2a2a"
            tertiary_bg = "#303030"
            text_color = "#c5160a"
            border_color = "#c5160a"
            thumb_bg = "#333333"
        else:
            theme = qdarktheme.load_stylesheet("light")
            bg_color = "#ffffff"
            secondary_bg = "#f5f5f5"
            tertiary_bg = "#e0e0e0"
            text_color = "#c5160a"
            border_color = "#c5160a"
            thumb_bg = "#e0e0e0"

        # Replace colors with our red theme color
        theme = theme.replace("#3498db", "#c5160a")  # Primary color
        theme = theme.replace("#2980b9", "#a01208")  # Darker primary for hover

        # Add comprehensive styling for all elements
        theme += f"""
            /* Menu Styling */
            QMenu {{
                color: {text_color};
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 5px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 30px 8px 20px;
                border-radius: 3px;
                margin: 2px;
                font-size: 14px;
            }}
            QMenu::item:selected {{
                background-color: rgba(197, 22, 10, 0.1);
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border_color};
                margin: 5px 15px;
            }}
            QMenu::item:disabled {{
                color: #666666;
            }}

            /* Rest of your existing styles... */
            {self._get_existing_styles(bg_color, secondary_bg, tertiary_bg, text_color, border_color, thumb_bg)}
        """
        
        self.setStyleSheet(theme)
        
        # Update title bar background
        self._title_bar.setStyleSheet(f"background-color: {bg_color};")

    def _get_existing_styles(self, bg_color, secondary_bg, tertiary_bg, text_color, border_color, thumb_bg):
        """Return existing styles to maintain other UI elements."""
        return f"""
            QMainWindow, QDialog {{
                background-color: {bg_color};
            }}
            
            /* Text Colors */
            QLabel, QCheckBox, QRadioButton, QPushButton, QToolButton,
            QTabBar::tab, QMenuBar, QLineEdit, QTextEdit, QPlainTextEdit,
            QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QDateTimeEdit,
            QGroupBox, QStatusBar {{
                color: {text_color};
            }}
            
            /* Input Fields */
            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
            QTimeEdit, QDateEdit, QDateTimeEdit, QComboBox {{
                background-color: {secondary_bg};
                border: 1px solid {border_color};
                border-radius: 3px;
                padding: 2px 5px;
                selection-background-color: rgba(197, 22, 10, 0.2);
                selection-color: {text_color};
            }}
            
            /* ComboBox Styling */
            QComboBox::drop-down {{
                border: none;
                color: {text_color};
            }}
            QComboBox::down-arrow {{
                image: none;
                border: 2px solid {text_color};
                width: 6px;
                height: 6px;
                border-bottom: none;
                border-right: none;
                transform: rotate(45deg);
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                selection-background-color: rgba(197, 22, 10, 0.1);
                selection-color: {text_color};
            }}
            
            /* Buttons */
            QPushButton {{
                background-color: {secondary_bg};
                border: 1px solid {border_color};
                border-radius: 3px;
                padding: 5px 15px;
            }}
            QPushButton:hover {{
                background-color: rgba(197, 22, 10, 0.1);
            }}
            QPushButton:pressed {{
                background-color: rgba(197, 22, 10, 0.2);
            }}
            
            /* Group Boxes */
            QGroupBox {{
                border: 1px solid {border_color};
                margin-top: 5px;
                padding-top: 10px;
                background-color: {bg_color};
            }}
            QGroupBox::title {{
                color: {text_color};
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                background-color: {bg_color};
            }}
            
            /* Tables */
            QTableWidget {{
                color: {text_color};
                background-color: {secondary_bg};
                gridline-color: {border_color};
                border: 1px solid {border_color};
                selection-background-color: rgba(197, 22, 10, 0.1);
                selection-color: {text_color};
            }}
            QHeaderView::section {{
                color: {text_color};
                background-color: {tertiary_bg};
                border: 1px solid {border_color};
            }}
            
            /* Progress Bars */
            QProgressBar {{
                color: {text_color};
                background-color: {secondary_bg};
                border: 1px solid {border_color};
                border-radius: 2px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {border_color};
            }}
            
            /* Tab Widget */
            QTabWidget::pane {{
                border: 1px solid {border_color};
                background-color: {bg_color};
            }}
            QTabBar::tab {{
                background-color: {secondary_bg};
                border: 1px solid {border_color};
                padding: 5px 10px;
                margin: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {border_color};
                color: {bg_color};
            }}
            
            /* Scroll Bars */
            QScrollBar {{
                background-color: {secondary_bg};
                border: 1px solid {border_color};
                width: 12px;
                height: 12px;
            }}
            QScrollBar::handle {{
                background-color: {border_color};
                border-radius: 2px;
                margin: 2px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                background: none;
                border: none;
            }}
            
            /* Status Bar */
            QStatusBar {{
                border-top: 1px solid {border_color};
                background-color: {bg_color};
            }}
            
            /* Tooltips */
            QToolTip {{
                color: {text_color};
                background-color: {bg_color};
                border: 1px solid {border_color};
            }}
            
            /* Text Selection */
            QWidget {{
                selection-background-color: rgba(197, 22, 10, 0.2);
                selection-color: {text_color};
            }}
            
            /* Thumbnail Placeholder */
            QLabel[class="thumbnail-placeholder"] {{
                background-color: {thumb_bg};
                border: 1px solid {border_color};
                border-radius: 3px;
            }}
        """


# ----------------------------------------------------------------------------
# Main application entry point
# ----------------------------------------------------------------------------

def load_application_font(app):
    """Load the application font with proper error handling and fallbacks."""
    # Try multiple possible font paths
    possible_font_paths = [
        os.path.join("assets", "ReadexPro-Regular.ttf"),  # Development path
        os.path.join(os.path.dirname(sys.executable), "assets", "ReadexPro-Regular.ttf"),  # Built path
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ReadexPro-Regular.ttf"),  # Module path
    ]
    
    font_loaded = False
    for font_path in possible_font_paths:
        if os.path.exists(font_path):
            try:
                fid = QFontDatabase.addApplicationFont(font_path)
                if fid != -1:
                    font_family = QFontDatabase.applicationFontFamilies(fid)[0]
                    app.setFont(QFont(font_family, 10))
                    logger.info(f"Successfully loaded custom font from {font_path}")
                    font_loaded = True
                    break
                else:
                    logger.warning(f"Failed to load custom font from {font_path}")
            except Exception as e:
                logger.warning(f"Error loading font from {font_path}: {str(e)}")
    
    if not font_loaded:
        logger.warning("Custom font not found or failed to load. Using fallback fonts.")
        # Try system fonts in order of preference
        fallback_fonts = ["Segoe UI", "Arial", "Helvetica", "Verdana"]
        for font_name in fallback_fonts:
            if QFontDatabase.hasFamily(font_name):
                app.setFont(QFont(font_name, 10))
                logger.info(f"Using fallback font: {font_name}")
                break
        else:
            # If no fallback fonts are available, use the system default
            app.setFont(QFont())
            logger.info("Using system default font")

def get_ffmpeg_path():
    """Get the path to FFmpeg executable in the assets folder."""
    try:
        # Try to get the path relative to the executable (for PyInstaller)
        base_path = sys._MEIPASS
    except Exception:
        # Fall back to the current directory
        base_path = os.path.abspath(".")
    
    # Check for FFmpeg in assets folder
    ffmpeg_path = join(base_path, "assets", "ffmpeg.exe")
    if os.path.exists(ffmpeg_path):
        return ffmpeg_path
    
    # If not found in assets, try to find it in PATH
    ffmpeg_path = "ffmpeg"
    try:
        subprocess.run([ffmpeg_path, "-version"], 
                      capture_output=True, 
                      check=True,
                      startupinfo=get_startupinfo())
        return ffmpeg_path
    except (subprocess.SubprocessError, FileNotFoundError):
        raise RuntimeError("FFmpeg not found. Please ensure FFmpeg is installed and in your PATH or in the assets folder.")

# Add this function after get_ffmpeg_path()
def get_app_root():
    """Get the application's root directory."""
    return os.getcwd()  # Always return the current working directory

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application icon
    icon_path = get_resource_path(os.path.join("assets", "youtube_logo.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Load application font
    load_application_font(app)
    
    # Apply dark theme with red text
    dark_theme = qdarktheme.load_stylesheet("dark")
    # Replace all text colors with red
    dark_theme = dark_theme.replace("#3498db", "#c5160a")  # Primary color
    dark_theme = dark_theme.replace("#F0F0F0", "#c5160a")  # Text color
    dark_theme = dark_theme.replace("#FFFFFF", "#c5160a")  # White text
    dark_theme = dark_theme.replace("#E0E0E0", "#c5160a")  # Light text
    dark_theme = dark_theme.replace("#C0C0C0", "#c5160a")  # Gray text
    dark_theme = dark_theme.replace("#A0A0A0", "#c5160a")  # Darker gray text
    
    # Add additional styles for specific elements
    dark_theme += """
        QLabel { color: #c5160a; }
        QLineEdit { color: #c5160a; }
        QTextEdit { color: #c5160a; }
        QComboBox { color: #c5160a; }
        QPushButton { color: #c5160a; }
        QCheckBox { color: #c5160a; }
        QGroupBox { color: #c5160a; }
        QTableWidget { color: #c5160a; }
        QHeaderView::section { color: #c5160a; }
        QProgressBar { color: #c5160a; }
        QTabWidget::pane { color: #c5160a; }
        QTabBar::tab { color: #c5160a; }
    """
    
    app.setStyleSheet(dark_theme)
    
    # Create and show main window
    w = MainWindow()
    w.show()
    
    # Run application
    sys.exit(app.exec())