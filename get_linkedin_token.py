# get_linkedin_token.py
# LinkedIn AI Daily Post Automation — One-Time OAuth2 Token Helper
#
# PURPOSE: Run this script ONCE to get your LinkedIn Access Token and Person URN.
#          Copy both values into config.py.
#
# PREREQUISITES — Add these 2 products to your LinkedIn App (both free):
#   1. "Share on LinkedIn"                          → gives w_member_social scope
#   2. "Sign In with LinkedIn using OpenID Connect" → gives openid + profile scope
#   Go to: developer.linkedin.com → Your App → Products tab → Request Access
#
# USAGE: python get_linkedin_token.py

import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse

# ── Fill these in before running (or set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET env variables) ─
import os
CLIENT_ID     = os.environ.get("LINKEDIN_CLIENT_ID", "773k9a8lhm8m2a")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")

# Prompt if not set in environment
if not CLIENT_SECRET:
    try:
        CLIENT_SECRET = input("Enter LinkedIn Client Secret (from developer portal): ").strip()
    except (KeyboardInterrupt, EOFError):
        pass

REDIRECT_URI  = "http://localhost:8000/callback"
# ─────────────────────────────────────────────────────────────────────────────

_captured_code = None


class _OAuthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the ?code= from LinkedIn's redirect."""

    def do_GET(self):
        global _captured_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style='font-family:sans-serif;text-align:center;padding:60px;background:#f0f0f0'>
                <h2 style='color:green'>&#x2705; Authorization Successful!</h2>
                <p>You can close this tab and return to your terminal.</p>
                </body></html>
            """)
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            desc  = params.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2 style='color:red'>&#x274C; {error}</h2><p>{desc}</p></body></html>".encode()
            )
            _captured_code = f"ERROR:{error}:{desc}"
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Waiting for LinkedIn redirect...")

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs


def _start_local_server():
    """Start a one-shot local HTTP server on port 8000."""
    server = HTTPServer(("localhost", 8000), _OAuthHandler)
    server.handle_request()
    server.server_close()


def main():
    """Run the LinkedIn OAuth2 Authorization Code Flow."""
    global _captured_code

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\n❌ Fill in CLIENT_ID and CLIENT_SECRET at the top of this file.\n")
        return

    print("\n" + "=" * 60)
    print("   LinkedIn OAuth2 Token Helper")
    print("=" * 60)

    # Start local server BEFORE opening the browser
    print("\n📌 Step 1: Starting local callback server on port 8000...")
    server_thread = threading.Thread(target=_start_local_server, daemon=True)
    server_thread.start()

    # Build auth URL — scopes: w_member_social (posting) + openid + profile (URN)
    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=w_member_social%20openid%20profile"
    )

    print("📌 Step 2: Opening LinkedIn in your browser — log in and click Allow...")
    webbrowser.open(auth_url)

    print("📌 Step 3: Waiting for LinkedIn to redirect to localhost:8000...")
    server_thread.join(timeout=120)

    if not _captured_code:
        print("\n❌ Timed out. Please try again.\n")
        return

    if str(_captured_code).startswith("ERROR:"):
        parts = _captured_code.split(":", 2)
        error = parts[1] if len(parts) > 1 else "unknown"
        desc  = parts[2] if len(parts) > 2 else ""
        print(f"\n❌ LinkedIn error: {error}")
        print(f"   Details: {desc}")
        if "unauthorized_scope" in error or "unauthorized_scope" in desc:
            print("\n💡 FIX: Add these 2 products to your LinkedIn app at developer.linkedin.com:")
            print("   → Products tab → 'Share on LinkedIn'")
            print("   → Products tab → 'Sign In with LinkedIn using OpenID Connect'")
        return

    code = _captured_code
    print("   ✅ Authorization code captured automatically.")

    # Exchange code for access token
    print("📌 Step 4: Exchanging code for access token...")
    token_response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=15,
    )

    if token_response.status_code != 200:
        print(f"\n❌ Token exchange failed: {token_response.text}\n")
        return

    tokens = token_response.json()
    access_token = tokens.get("access_token")

    if not access_token:
        print(f"\n❌ No access token in response: {tokens}\n")
        return

    # Fetch Person URN via /v2/userinfo (requires openid + profile scopes)
    print("📌 Step 5: Fetching your LinkedIn Person URN...")
    person_urn = None
    profile_r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if profile_r.status_code == 200:
        sub = profile_r.json().get("sub", "")
        if sub:
            person_urn = f"urn:li:person:{sub}"

    # Fallback — ask user to enter their member ID manually
    if not person_urn:
        print("\n⚠️  Could not fetch Person URN automatically.")
        print("   To find it manually:")
        print("   1. Go to linkedin.com → click your profile picture → 'View Profile'")
        print("   2. Look at the URL: linkedin.com/in/your-name/")
        print("   3. Open DevTools (F12) → Console → paste:")
        print("      document.cookie.match(/li_a=([^;]+)/)?.[1]")
        print("   OR contact LinkedIn support for your member ID.")
        member_id = input("\n   Paste your member ID (alphanumeric only, no 'urn:li:person:'): ").strip()
        person_urn = f"urn:li:person:{member_id}" if member_id else "FILL_IN_MANUALLY"

    # Print final values
    print("\n" + "=" * 60)
    print("   ✅ SUCCESS — Copy these into config.py")
    print("=" * 60)
    print(f'\nLINKEDIN_ACCESS_TOKEN = "{access_token}"')
    print(f'\nLINKEDIN_PERSON_URN   = "{person_urn}"')
    print("\n" + "=" * 60)
    print("⚠️  Token expires in 60 days. Re-run this script to refresh.")
    print("⚠️  Never commit these values to version control.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
