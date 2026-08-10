# MerchOps Agent LAN Setup

Use this when you want to open this Flask project from another PC on the same local network.

## Start the app

For smoother LAN hosting, install Waitress once on the host PC:

```powershell
python -m pip install waitress
```

From this project folder, run:

```bat
start_lan.bat
```

Or run directly:

```powershell
python run_lan.py
```

The terminal will show URLs like:

```text
LAN access: http://192.168.0.25:5000
Health check: http://192.168.0.25:5000/lan-health
```

Open that URL on the other PC.

First test the health check on the other PC:

```text
http://HOST-PC-IP:5000/lan-health
```

If the health check is fast but the app page is slow, the web server is reachable and the delay is usually database/report loading.

## Allow Windows Firewall

If the other PC cannot open the site, run PowerShell as Administrator on the host PC and allow port `5000`:

```powershell
New-NetFirewallRule -DisplayName "MerchOps Agent Flask LAN 5000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000
```

## Change Port

If port `5000` is busy:

```powershell
$env:LAN_PORT="5050"
python run_lan.py
```

Then open:

```text
http://HOST-PC-IP:5050
```

## Smoother LAN Settings

You can increase the server worker threads before starting:

```powershell
$env:LAN_THREADS="20"
python run_lan.py
```

If you start from `start_lan.bat`, it uses the default `12` threads.

## If It Loads Then Disconnects

1. Install Waitress:

```powershell
python -m pip install waitress
```

2. Start again:

```powershell
python run_lan.py
```

3. Test from the other PC:

```text
http://HOST-PC-IP:5000/lan-health
```

4. If health check works but login/report pages are slow, check SQL Server access and report queries on the host PC.

## Notes

- The host PC and the other PC must be on the same LAN/Wi-Fi.
- Keep the terminal window running while using the app.
- SQL Server access still depends on your existing database connection and network permissions.
