.PHONY: build test clean publish test-publish install

# Build the package
build:
	python -m build

# Run tests (if you add them)
test:
	pytest

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf __pycache__
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete

# Install locally
install:
	pip install -e .

# Publish to TestPyPI
test-publish: clean build
	twine upload --repository testpypi dist/*

# Publish to PyPI
publish: clean build
	twine upload dist/*

# Build executables
build-exe-cli:
	pyinstaller --name=watchdock --onefile watchdock/main.py

build-exe-gui:
	pyinstaller --name=WatchDock --windowed --onefile watchdock/gui_main.py

build-exe-all: build-exe-cli build-exe-gui

# Check package before publishing
check:
	twine check dist/*

