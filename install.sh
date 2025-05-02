#!/bin/bash

# Check if whois is installed
if ! command -v whois &> /dev/null; then
    echo "Error: whois is not installed"
    echo "Please install it using: sudo apt install whois"
    exit 1
fi

# Check if Python 3.12+ is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if (( $(echo "$python_version < 3.12" | bc -l) )); then
    echo "Error: Python 3.12 or higher is required"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
echo "Installing dependencies..."
pip install -r requirements.txt

# Install the package in development mode
pip install -e .

echo "Installation complete! You can now run 'python main.py' directly."