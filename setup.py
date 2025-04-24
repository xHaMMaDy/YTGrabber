from setuptools import setup, find_packages

setup(
    name="YTGrabber",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "PySide6>=6.7.0",
        "yt-dlp>=2024.05.18",
        "requests>=2.31.0",
        "qdarktheme>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "ytgrabber=src.main:main",
        ],
    },
    author="Ibrahim Hammad (HaMMaDy)",
    author_email="xhammady@gmail.com",
    description="A powerful YouTube video downloader with modern UI",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/xhammady/YTGrabber",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
) 