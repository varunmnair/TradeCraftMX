# TradeCraftX

TradeCraftX is a multi-broker trading automation and analysis CLI tool designed for Zerodha and Upstox. It features AI-powered analysis using Google Gemini and Groq to help refine entry strategies, analyze holdings, and manage risk.

## Features

- **Multi-Broker Support**: Seamlessly switch between Zerodha (Kite) and Upstox.
- **AI Analyst**: Integrated with Google Gemini for intelligent market insights and entry level refinement.
- **Holdings Analysis**: Analyze ROI, weighted returns, and filter holdings.
- **GTT Automation**: Analyze variance and automate GTT (Good Till Triggered) orders.
- **Risk Management**: Tools to apply risk management rules to your trading plan.

## Prerequisites

- Python 3.10 or higher
- Accounts with Zerodha or Upstox (with API access enabled)
- API Keys for Google Gemini (and optionally Groq)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/TradeCraftX.git
   cd TradeCraftX
   ```

2. **Set up the environment:**

   **Windows:**
   Double-click `setup.bat` or run:
   ```cmd
   setup.bat
   ```

   **Mac/Linux:**
   Run the setup script:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Configure Credentials:**
   - Rename `.env.example` to `.env`.
   - Open `.env` and fill in your API keys for Zerodha, Upstox, and Gemini.

4. **Data Setup:**
   Before running the project, ensure the following data files are in place:
   
   - **`name-symbol-mapping.csv`**: A mapping of stock symbols to their full names.
     ```csv
     Symbol,Name
     RELIANCE,Reliance Industries Ltd
     TCS,Tata Consultancy Services Ltd
     ```
   - **Entry Levels CSV**: A CSV file containing your planned entry levels.
     - **Naming Convention**: `{user_id}-{broker}-entry-levels.csv` (e.g., `NM9100-zerodha-entry-levels.csv`).
     - **Format**: Should contain columns like `Symbol`, `Entry_Level`, `Quantity`.
     ```csv
     Symbol,Entry_Level,Quantity,Note
     RELIANCE,2350,10,Support level
     TCS,3400,5,Long term
     ```
     - *Note*: Ensure the filename matches the User ID you input when running the application.

## Usage

To start the application, simply run the start script for your OS.

**Windows:**
Double-click `run.bat` or run:
```cmd
run.bat
```

**Mac/Linux:**
```bash
chmod +x run.sh
./run.sh
```

Alternatively, you can run it manually via Python:
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
python menu_cli.py
```