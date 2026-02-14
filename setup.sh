#!/bin/bash
echo "Setting up TradeCraftX Environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created."
fi

source venv/bin/activate
pip install -r requirements.txt
echo "Setup complete. You can now run './run.sh'."