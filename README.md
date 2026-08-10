# MerchOps Agent

Flask-based merchandising operations agent with modules for inventory, email workflows, dashboards, reports, alerts, users, organization settings, and data chatbot workflows.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create a local `.env` file with the required settings:

   ```env
   SECRET_KEY=change-me
   SQL_SERVER=your-sql-server
   SQL_DATABASE=your-database
   SQL_DRIVER=ODBC Driver 17 for SQL Server
   SQL_TRUSTED=yes
   ANTHROPIC_API_KEY=your-api-key
   ```

4. Run the app:

   ```powershell
   python run.py
   ```

The app starts on `http://localhost:5000` by default.

## Notes

Local runtime files are intentionally ignored by Git, including `.env`, logs, caches, generated chatbot exports/history, face data, instance files, and demo videos.
