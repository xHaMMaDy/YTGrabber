# YTGrabber 🎥

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Qt](https://img.shields.io/badge/Qt-6.7+-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/xHaMMaDy/YTGrabber?style=for-the-badge)](https://github.com/xHaMMaDy/YTGrabber/stargazers)

A powerful YouTube video downloader with a modern Qt interface, built with Python and PySide6.

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Screenshots](#screenshots) • [Contributing](#contributing)

</div>

## ✨ Features

### Core Features
- 🎥 Download videos in various formats and qualities
- 🎵 Extract audio in MP3 format
- ✂️ Video trimming with precise timing
- 📋 Playlist download support
- 📦 Batch download capability
- 📊 Download history tracking
- 🌓 Dark/Light theme support
- 📈 Real-time progress tracking with speed and ETA
- 🖼️ Thumbnail preview and saving

### Video Options
- 📹 Support for multiple video qualities (4K, 1080p, 720p, etc.)
- 🎞️ Various video formats (MP4, WebM, etc.)
- 🔊 Separate audio track download
- ⚡ Best quality auto-selection

### Advanced Features
- ✂️ Video Trimming
  - Set precise start/end times
  - Preview trim selection
  - Maintain original quality
  - Separate audio/video processing
  
- 📋 Playlist Management
  - Download entire playlists
  - Select specific videos
  - Quality presets for batch downloads
  - Progress tracking per video
  
- 📦 Batch Processing
  - Multiple URL support
  - Concurrent downloads
  - Queue management
  - Individual progress tracking

- 🛠️ Additional Tools
  - Thumbnail extraction
  - Format inspection
  - Download speed limiter
  - Custom output templates

## 🚀 Installation

### Prerequisites
- Python 3.12 or higher
- FFmpeg (included in assets folder)
- Internet connection

### Method 1: From Source
1. Clone the repository:
```bash
git clone https://github.com/xHaMMaDy/YTGrabber.git
cd YTGrabber
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python src/main.py
```

### Method 2: Binary Release
1. Download the latest release from the [Releases](https://github.com/xHaMMaDy/YTGrabber/releases) page
2. Extract the archive
3. Run `YTGrabber.exe`

## 📖 Usage

### Basic Download
1. Launch YTGrabber
2. Paste a YouTube URL
3. Click "Fetch Info" to load video details
4. Select desired format and quality
5. Click "Download"

### Audio Extraction
1. Select "Audio Only" from the download type
2. Choose preferred audio quality
3. Click "Download" to save as MP3

### Video Trimming
1. Enable the trim option
2. Set start and end times
3. Preview if needed
4. Download the trimmed section

### Playlist Download
1. Paste a playlist URL
2. Select videos to download
3. Choose quality preset
4. Start batch download

## 📸 Screenshots

<div align="center">
  <img src="https://i.imgur.com/6rzQVkp.png" alt="Main Window" width="900"/>
  <p><em>Main application window with dark theme and video information</em></p>
  
  <br/>
  
  <img src="https://i.imgur.com/hML5r5V.png" alt="Playlist Download Interface" width="900"/>
  <p><em>Playlist download interface with batch processing options</em></p>
</div>

## ⚙️ Configuration

### Output Settings
- Custom download directory
- Filename templates
- Organize by channel/playlist

### Network Settings
- Download speed limit
- Concurrent downloads
- Proxy support
- Retry attempts

### Interface Settings
- Dark/Light theme
- Language selection
- Progress bar style
- Notification preferences

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

### Development Setup
1. Fork the repository
2. Create a virtual environment
3. Install development dependencies:
```bash
pip install -r requirements-dev.txt
```
4. Make your changes
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Core downloading functionality
- [PySide6](https://www.qt.io/qt-for-python) - Modern UI framework
- [FFmpeg](https://ffmpeg.org/) - Media processing
- [qdarktheme](https://github.com/5yutan5/PyQtDarkTheme) - Theme support

## 📧 Contact

Ibrahim Hammad (HaMMaDy) - [@xHaMMaDy](https://github.com/xHaMMaDy)

Project Link: [https://github.com/xHaMMaDy/YTGrabber](https://github.com/xHaMMaDy/YTGrabber)

---

<div align="center">
Made with ❤️ by HaMMaDy
</div>