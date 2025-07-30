from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess
import json
import threading
import uuid
import re
import os
import sys
import csv
from datetime import datetime

app = Flask(__name__)

# --- Settings ---
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "max_concurrent_downloads": 3,
    "output_dir": os.path.join(os.getcwd(), "downloads_web")
}
settings = {}

def load_settings():
    global settings
    if not os.path.exists(SETTINGS_FILE):
        settings = DEFAULT_SETTINGS
        return
    with open(SETTINGS_FILE, 'r') as f:
        settings = json.load(f)

def save_settings(data):
    global settings
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    settings = data

# --- Concurrency Control ---
download_semaphore = None

def initialize_semaphore():
    global download_semaphore
    download_semaphore = threading.Semaphore(settings.get("max_concurrent_downloads", 3))

# --- Task Management ---
tasks = {}

def get_startupinfo():
    """Get subprocess configuration to hide console window on Windows."""
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None

def sanitize_filename(filename: str) -> str:
    """Strip characters that are illegal on most filesystems."""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

def append_download_history(title: str, url: str, filepath: str, filesize: int):
    """Append a single row to local CSV history."""
    try:
        with open("download_history.csv", "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now().isoformat(), title, url, filepath, filesize])
    except IOError as e:
        print(f"Failed to write history: {e}") # Should use proper logging

def _actual_run_download(task_id, url, format_id, video_title):
    """The core download logic."""
    try:
        download_dir = settings.get("output_dir", DEFAULT_SETTINGS["output_dir"])
        os.makedirs(download_dir, exist_ok=True)

        safe_title = sanitize_filename(video_title)
        output_template = os.path.join(download_dir, f"{safe_title}_{format_id}.%(ext)s")

        cmd = ["yt-dlp", "--newline", "--progress", "-f", format_id, "-o", output_template, url]

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, universal_newlines=True, startupinfo=get_startupinfo()
        )

        for line in process.stdout:
            tasks[task_id]['log'] = tasks[task_id].get('log', '') + line
            if "[download]" in line and "%" in line:
                if match := re.search(r'(\d+\.\d+)%', line): tasks[task_id]['progress'] = float(match.group(1))
                if match := re.search(r'at\s+([^\s]+)', line): tasks[task_id]['speed'] = match.group(1)
                if match := re.search(r'ETA\s+([^\s]+)', line): tasks[task_id]['eta'] = match.group(1)

        process.wait()

        if process.returncode == 0:
            downloaded_files = [f for f in os.listdir(download_dir) if f.startswith(safe_title)]
            if downloaded_files:
                final_filepath_rel = downloaded_files[0]
                final_filepath_abs = os.path.join(download_dir, final_filepath_rel)
                filesize = os.path.getsize(final_filepath_abs)

                tasks[task_id]['status'] = 'completed'
                # Note: This filepath is for the browser, not for the server's file system access.
                # This assumes the output_dir is served statically, which is a security risk.
                # A better approach would be a dedicated /download/<task_id> route.
                # For now, we stick to the simple (but risky) static serving.
                tasks[task_id]['filepath'] = f"/downloads_web/{final_filepath_rel}"

                append_download_history(video_title, url, final_filepath_abs, filesize)
            else:
                tasks[task_id]['status'] = 'error'
                tasks[task_id]['error'] = "Download finished, but output file not found."
        else:
            tasks[task_id]['status'] = 'error'
            tasks[task_id]['error'] = f"Download failed with code {process.returncode}"

    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['error'] = str(e)

def run_download_wrapper(task_id, url, format_id, video_title):
    """Acquires semaphore and runs the download."""
    with download_semaphore:
        tasks[task_id]['status'] = 'downloading'
        _actual_run_download(task_id, url, format_id, video_title)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/fetch-info', methods=['POST'])
def fetch_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            url
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            startupinfo=get_startupinfo()
        )

        info = json.loads(result.stdout)
        return jsonify(info)

    except subprocess.CalledProcessError as e:
        return jsonify({'error': 'Failed to fetch video info', 'details': e.stderr}), 500
    except json.JSONDecodeError:
        return jsonify({'error': 'Failed to parse video info'}), 500
    except Exception as e:
        return jsonify({'error': 'An unexpected error occurred', 'details': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    url = request.json.get('url')
    format_id = request.json.get('format_id')
    title = request.json.get('title', 'video')

    if not url or not format_id:
        return jsonify({'error': 'URL and format_id are required'}), 400

    task_id = str(uuid.uuid4())
    tasks[task_id] = {'status': 'queued', 'progress': 0}

    thread = threading.Thread(target=run_download_wrapper, args=(task_id, url, format_id, title))
    thread.start()

    return jsonify({'task_id': task_id})

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def post_settings():
    new_settings = request.json
    save_settings(new_settings)
    # Note: For settings like concurrency, a restart is needed to apply.
    # We can inform the user on the frontend.
    initialize_semaphore() # Re-initialize semaphore with new settings
    return jsonify({"status": "success"})

@app.route('/downloads_web/<path:filename>')
def serve_download(filename):
    download_dir = settings.get("output_dir", DEFAULT_SETTINGS["output_dir"])
    return send_from_directory(download_dir, filename, as_attachment=True)

@app.route('/api/status/<task_id>')
def task_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)

@app.route('/api/fetch-playlist', methods=['POST'])
def fetch_playlist():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--flat-playlist",
            url
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            startupinfo=get_startupinfo()
        )

        # yt-dlp with --dump-json and --flat-playlist outputs one JSON object per line
        videos = []
        for line in result.stdout.strip().split('\n'):
            videos.append(json.loads(line))

        return jsonify(videos)

    except subprocess.CalledProcessError as e:
        return jsonify({'error': 'Failed to fetch playlist info', 'details': e.stderr}), 500
    except json.JSONDecodeError:
        return jsonify({'error': 'Failed to parse playlist info'}), 500
    except Exception as e:
        return jsonify({'error': 'An unexpected error occurred', 'details': str(e)}), 500

@app.route('/api/history')
def history():
    history_data = []
    if os.path.exists("download_history.csv"):
        with open("download_history.csv", "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                history_data.append({
                    "date": row[0],
                    "title": row[1],
                    "url": row[2],
                    "filepath": row[3],
                    "filesize": row[4]
                })
    return jsonify(history_data)

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    try:
        if os.path.exists("download_history.csv"):
            os.remove("download_history.csv")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    load_settings()
    initialize_semaphore()
    app.run(debug=True, threaded=True)
