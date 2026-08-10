from dotenv import load_dotenv
load_dotenv()

import os
import socket
import sys

def local_ip_addresses():
    addresses = set()
    hostname = socket.gethostname()

    try:
        for address in socket.gethostbyname_ex(hostname)[2]:
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        addresses.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass

    return sorted(addresses)


if __name__ == "__main__":
    from app import create_app

    host = os.getenv("LAN_HOST", "0.0.0.0")
    port = int(os.getenv("LAN_PORT", "5000"))
    debug = os.getenv("LAN_DEBUG", "0").lower() in {"1", "true", "yes"}
    threads = int(os.getenv("LAN_THREADS", "12"))
    use_https = os.getenv("LAN_HTTPS", "0").lower() in {"1", "true", "yes"}
    app = create_app()

    @app.get("/lan-health")
    def lan_health():
        return "MerchOps Agent LAN server is running", 200

    scheme = "https" if use_https else "http"
    print("\nMerchOps Agent LAN server")
    print(f"Local machine: {scheme}://127.0.0.1:{port}")
    for address in local_ip_addresses():
        print(f"LAN access:    {scheme}://{address}:{port}")
        print(f"Health check:  {scheme}://{address}:{port}/lan-health")
    if use_https:
        print("\nHTTPS mode is enabled for camera access from phones/other LAN devices.")
        print("The browser may show a certificate warning. Continue/advanced once for this local server.\n")
        app.run(
            host=host,
            port=port,
            debug=debug,
            threaded=True,
            use_reloader=False,
            ssl_context="adhoc",
        )
        sys.exit(0)

    print("\nUse one of the LAN access URLs from another PC on the same network.")
    print("For face camera login on other devices, start HTTPS mode with start_lan_https.bat.\n")

    try:
        from waitress import serve
    except ImportError:
        print("Waitress is not installed. Using Flask threaded server fallback.")
        print("For smoother LAN access, install once with: python -m pip install waitress\n")
        app.run(
            host=host,
            port=port,
            debug=debug,
            threaded=True,
            use_reloader=False,
        )
    else:
        print(f"Using Waitress production server with {threads} threads.\n")
        try:
            serve(
                app,
                host=host,
                port=port,
                threads=threads,
                connection_limit=200,
                channel_timeout=180,
                cleanup_interval=30,
                url_scheme="http",
            )
        except OSError as exc:
            print(f"\nCould not start LAN server on port {port}: {exc}")
            print("Try another port, for example:")
            print("  set LAN_PORT=5050")
            print("  python run_lan.py")
            sys.exit(1)
