"""
Setup script for WatchDock.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding='utf-8') if readme_file.exists() else ""

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_file.exists():
    requirements = [
        line.strip()
        for line in requirements_file.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="watchdock",
    version="0.1.1",
    description="A local, self-hosted file monitoring and organization tool using AI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="WatchDock Team",
    author_email="hehan.zhao@outlook.com",
    url="https://github.com/Z-MarkUs/watchdock",
    project_urls={
        "Bug Reports": "https://github.com/Z-MarkUs/watchdock/issues",
        "Source": "https://github.com/Z-MarkUs/watchdock",
        "Documentation": "https://github.com/Z-MarkUs/watchdock#readme",
    },
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "watchdock=watchdock.main:main",
            "watchdock-gui=watchdock.gui_main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)

