# main.py
# LinkedIn AI Daily Post Automation — Core Workflow
# Version: 1.0.0
#
# Runs daily at the configured time and:
#   1. Picks today's AI/Tech topic from a rotation list
#   2. Checks Google Sheets for duplicate (already posted today?)
#   3. Researches the topic via DuckDuckGo Instant Answer API
#   4. Generates a LinkedIn post via Groq (Llama 3 70B)
#   5. Quality-checks the post via a second Groq call (scores 1–10)
#   6. Generates an image via Pollinations.AI (Flux model, free)
#   7. Uploads the image and publishes the post to LinkedIn
#   8. Logs the result to Google Sheets
#   9. Sends an email notification via Gmail SMTP (success or failure)
#
# Run: python main.py
# Test immediately: uncomment run_workflow() near the bottom of this file.

# ── Standard Library ──────────────────────────────────────────────────────────
import json
import logging
import os
import random
import re
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Third-Party Libraries ─────────────────────────────────────────────────────
import requests
import gspread
import schedule
from google.oauth2.service_account import Credentials

# ── Local Config ──────────────────────────────────────────────────────────────
import config  # All API keys and settings live here — never imported inside functions


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPT DIRECTORY — all relative paths resolve from here, not from cwd.
# This makes the script work correctly regardless of where you run it from.
# ─────────────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# Writes to both console and logs/automation.log
# ─────────────────────────────────────────────────────────────────────────────
_logs_dir = os.path.join(_SCRIPT_DIR, "logs")
os.makedirs(_logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(_logs_dir, "automation.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC ROTATION
# Cycles through daily using day-of-year % len(TOPICS) — never day-of-week.
# Add or edit topics here. Each entry MUST have: topic, company, hashtags.
# ─────────────────────────────────────────────────────────────────────────────
TOPICS = [
    {
        "topic": "OpenAI latest news and GPT updates",
        "company": "OpenAI",
        "hashtags": "#OpenAI #GPT #ArtificialIntelligence #AI #MachineLearning",
    },
    {
        "topic": "Google DeepMind and Gemini AI developments",
        "company": "Google",
        "hashtags": "#Google #Gemini #DeepMind #AI #Tech",
    },
    {
        "topic": "Meta AI and Llama model updates",
        "company": "Meta",
        "hashtags": "#Meta #LlamaAI #AI #MachineLearning #OpenSource",
    },
    {
        "topic": "Microsoft Azure AI and Copilot news",
        "company": "Microsoft",
        "hashtags": "#Microsoft #Copilot #AzureAI #AI #Productivity",
    },
    {
        "topic": "Apple AI features and machine learning news",
        "company": "Apple",
        "hashtags": "#Apple #AppleIntelligence #AI #Tech #Innovation",
    },
    {
        "topic": "NVIDIA AI chips and GPU technology news",
        "company": "NVIDIA",
        "hashtags": "#NVIDIA #GPU #AI #DeepLearning #Semiconductors",
    },
    {
        "topic": "General AI breakthroughs and research news",
        "company": "AI Industry",
        "hashtags": "#AI #ArtificialIntelligence #MachineLearning #FutureOfWork #Tech",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. GOOGLE SHEETS — Authentication
# ─────────────────────────────────────────────────────────────────────────────
def get_sheet():
    """Authenticate with Google Sheets API and return the target worksheet."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    # Resolve credentials path relative to this script file, not the cwd
    creds_path = os.path.join(_SCRIPT_DIR, config.GOOGLE_CREDENTIALS_FILE)
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(config.GOOGLE_SHEET_ID).worksheet(config.SHEET_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# 2. DUPLICATE DETECTION
# Reads column A (Date) — if today's date exists, we already posted today.
# ─────────────────────────────────────────────────────────────────────────────
def is_duplicate(date_str):
    """Return True if today's date is already present in the Google Sheet (column A)."""
    try:
        sheet = get_sheet()
        dates = sheet.col_values(1)  # Column A = Date
        return date_str in dates
    except Exception as e:
        err_detail = str(e) or "(no message)"
        log.warning(f"⚠️ Duplicate check failed: {type(e).__name__}: {err_detail}. Continuing anyway (fail-open).")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. GOOGLE SHEETS LOGGING
# Appends one row per run. Column order is fixed — do not change it.
# ─────────────────────────────────────────────────────────────────────────────
def log_to_sheet(date, topic, company, post, image_url, quality_score, status):
    """Append a result row to the Google Sheet (non-critical — logs warning on failure)."""
    try:
        sheet = get_sheet()
        sheet.append_row(
            [
                date,                           # A — Date       YYYY-MM-DD
                topic,                          # B — Topic
                company,                        # C — Company
                post,                           # D — Post text
                image_url,                      # E — ImageURL
                quality_score,                  # F — QualityScore
                status,                         # G — Status
                datetime.now().isoformat(),     # H — PostedAt
            ]
        )
        log.info("✅ Logged to Google Sheets")
    except Exception as e:
        err_detail = str(e) or "(no message)"
        log.warning(f"⚠️ Google Sheets log failed (non-critical): {type(e).__name__}: {err_detail}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. EMAIL NOTIFICATIONS (Gmail SMTP)
# Non-critical — if email fails, workflow continues. Uses stdlib smtplib only.
# ─────────────────────────────────────────────────────────────────────────────
def send_email(subject: str, body: str) -> None:
    """Send a notification email via Gmail SMTP (SSL). Non-critical — logs warning on failure."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.GMAIL_SENDER
        msg["To"]      = config.GMAIL_RECEIVER
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.GMAIL_SENDER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_SENDER, config.GMAIL_RECEIVER, msg.as_string())

        log.info("📧 Email notification sent")
    except smtplib.SMTPAuthenticationError:
        log.warning("⚠️ Email failed: Gmail authentication error. Check GMAIL_APP_PASSWORD in config.py")
    except smtplib.SMTPException as e:
        log.warning(f"⚠️ Email failed (SMTP error): {e}")
    except Exception as e:
        log.warning(f"⚠️ Email failed (non-critical): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. RESEARCH
# Queries DuckDuckGo Instant Answer API — free, no key required.
# Falls back to a plain topic description if the API returns empty data.
# ─────────────────────────────────────────────────────────────────────────────
def research_topic(topic, company):
    """Fetch research context from DuckDuckGo Instant Answer API.

    Returns a formatted summary string to pass into the post generation prompt.
    Falls back to a generic topic description if DDG returns insufficient data.
    """
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": f"{topic} 2026",
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        lines = []
        if data.get("Abstract"):
            lines.append("Summary: " + data["Abstract"])
        if data.get("Answer"):
            lines.append("Answer: " + data["Answer"])
        if data.get("Definition"):
            lines.append("Definition: " + data["Definition"])
        for rt in data.get("RelatedTopics", [])[:5]:
            if isinstance(rt, dict) and rt.get("Text"):
                lines.append("Related: " + rt["Text"])

        summary = "\n".join(lines)

        # Fall back if DDG returned too little content
        if len(summary) < 30:
            summary = (
                f"Topic: {topic}\n"
                f"Company: {company}\n"
                f"Write about latest 2026 trends, announcements, and industry impact."
            )

        log.info(f"🔍 Research done ({len(lines)} results fetched)")
        return summary

    except requests.exceptions.Timeout:
        log.warning("⚠️ DuckDuckGo request timed out. Using fallback context.")
    except requests.exceptions.RequestException as e:
        log.warning(f"⚠️ DuckDuckGo request failed: {e}. Using fallback context.")
    except Exception as e:
        log.warning(f"⚠️ Research step error: {e}. Using fallback context.")

    return (
        f"Topic: {topic}\n"
        f"Company: {company}\n"
        f"Write about the latest 2026 developments and their impact on the AI industry."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. POST GENERATION
# Calls Groq API (Llama 3 70B) with creative temperature (0.8).
# Raises on failure — this is a critical step.
# ─────────────────────────────────────────────────────────────────────────────
def generate_post(research, topic, company, hashtags):
    """Generate a professional LinkedIn post using Groq Llama 3 70B.

    Raises requests.HTTPError on API failure (critical step — halts workflow).
    """
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 600,
        "temperature": 0.8,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a professional LinkedIn content creator specialising in AI and technology. "
                    "Write engaging, insightful posts in first-person. "
                    "Use max 3 emojis. Keep between 150 and 280 words. "
                    "Use line breaks for readability. Be professional yet conversational. "
                    "Never use clickbait. No more than 1 exclamation mark per post."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Write a LinkedIn post about {company} based on this research:\n\n{research}\n\n"
                    f"Topic focus: {topic}\n\n"
                    f"Structure:\n"
                    f"1. Start with a powerful hook (1 sentence)\n"
                    f"2. Share 2–3 key insights or news points\n"
                    f"3. Add a professional forward-looking perspective\n"
                    f"4. End with a thought-provoking question\n"
                    f"5. Final line — hashtags only: {hashtags} #LinkedIn #Technology\n\n"
                    f"Write the complete final post. No placeholders. No meta-commentary."
                ),
            },
        ],
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# 7. QUALITY CHECK
# Second Groq call with low temperature (0.2) for consistent scoring.
# Returns dict: {score: int, approved: bool, reason: str}
# ─────────────────────────────────────────────────────────────────────────────
def quality_check(post_text):
    """Score the generated post using a separate Groq call (1–10 scale).

    Returns a dict with keys: score (int), approved (bool), reason (str).
    Raises requests.HTTPError on API failure (critical step).
    """
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 100,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You are a professional LinkedIn content reviewer. Respond ONLY with valid JSON, no extra text.",
            },
            {
                "role": "user",
                "content": (
                    f"Review this LinkedIn post:\n\n{post_text}\n\n"
                    f"Score it 1–10 on: hook quality, professional tone, insights, and call-to-action.\n"
                    f'Respond with exactly this JSON: {{"score": 8, "approved": true, "reason": "brief one-line reason"}}\n'
                    f"approved must be true if score >= {config.QUALITY_MIN_SCORE}, otherwise false."
                ),
            },
        ],
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=20,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON — try direct parse first, then regex extraction as fallback
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", content, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            # If we truly can't parse, assume a passing score to avoid false rejection
            log.warning("⚠️ Quality check response parse failed — defaulting to approved.")
            result = {"score": 7, "approved": True, "reason": "JSON parse fallback"}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 8. IMAGE GENERATION
# Pollinations.AI — authenticated Flux API via gen.pollinations.ai.
# GET endpoint returns image bytes directly; Authorization header carries the key.
# Resolution: 1200×628px (LinkedIn optimal). Raises on failure — critical step.
# ─────────────────────────────────────────────────────────────────────────────
def generate_image(company, topic):
    """Generate a professional AI image via Pollinations.AI authenticated Flux API.

    Calls GET https://gen.pollinations.ai/image/{prompt}?model=flux&...
    with the secret API key in the Authorization header.
    The endpoint returns raw image bytes directly (no JSON wrapper).
    Returns tuple: (image_bytes, image_url).
    Raises Exception on failure (critical step — halts workflow).
    """
    prompt = (
        f"{company} artificial intelligence technology, futuristic digital landscape, "
        f"professional corporate style, blue and white colour scheme, cinematic lighting, "
        f"4K quality, no text, no logos, no watermarks"
    )

    seed = random.randint(1, 99999)
    encoded_prompt = requests.utils.quote(prompt)
    image_url = (
        f"https://gen.pollinations.ai/image/{encoded_prompt}"
        f"?model=flux&width=1200&height=628&seed={seed}&nologo=true"
    )

    log.info("🖼️  Generating image via Pollinations.AI Flux API (authenticated)...")

    headers = {
        "Authorization": f"Bearer {config.POLLINATIONS_API_KEY}",
    }

    r = requests.get(image_url, headers=headers, timeout=90)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "")
    if r.status_code == 200 and "image" in content_type:
        log.info(f"🖼️  Image ready ({len(r.content) // 1024} KB)")
        return r.content, image_url
    else:
        raise Exception(
            f"Pollinations.AI returned unexpected response: "
            f"HTTP {r.status_code}, Content-Type: {content_type}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 9. LINKEDIN IMAGE UPLOAD
# LinkedIn requires a 2-step process: initialize upload, then PUT image bytes.
# ─────────────────────────────────────────────────────────────────────────────
def linkedin_upload_image(image_bytes):
    """Upload an image to LinkedIn and return the image asset URN.

    Step 1: POST to initialize upload — receive uploadUrl and image asset URN.
    Step 2: PUT image bytes to the uploadUrl.
    Raises requests.HTTPError on any LinkedIn API error (critical).
    """
    headers = {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "LinkedIn-Version": "202506",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    # Step 1 — Initialize upload, get upload URL and image asset URN
    init_body = {"initializeUploadRequest": {"owner": config.LINKEDIN_PERSON_URN}}
    r = requests.post(
        "https://api.linkedin.com/rest/images?action=initializeUpload",
        headers=headers,
        json=init_body,
        timeout=15,
    )
    r.raise_for_status()
    upload_url  = r.json()["value"]["uploadUrl"]
    image_asset = r.json()["value"]["image"]

    # Step 2 — PUT image bytes directly to the signed upload URL
    upload_headers = {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "image/jpeg",
    }
    r2 = requests.put(upload_url, headers=upload_headers, data=image_bytes, timeout=30)
    r2.raise_for_status()

    log.info(f"☁️  Image uploaded to LinkedIn: {image_asset}")
    return image_asset


# ─────────────────────────────────────────────────────────────────────────────
# 10. LINKEDIN POST PUBLISHING
# Publishes the text + image to the LinkedIn feed as a public post.
# ─────────────────────────────────────────────────────────────────────────────
def linkedin_post(post_text, image_asset):
    """Publish a post with an attached image to LinkedIn (visibility: PUBLIC).

    Raises requests.HTTPError on any LinkedIn API error (critical).
    """
    headers = {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "LinkedIn-Version": "202506",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    body = {
        "author": config.LINKEDIN_PERSON_URN,
        "commentary": post_text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {
                "altText": "AI Technology Visual",
                "id": image_asset,
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = requests.post(
        "https://api.linkedin.com/rest/posts",
        headers=headers,
        json=body,
        timeout=15,
    )
    r.raise_for_status()
    log.info("🚀 Posted to LinkedIn!")


# ─────────────────────────────────────────────────────────────────────────────
# 11. MAIN WORKFLOW
# Orchestrates all steps. Critical failures halt and notify via Gmail email.
# Non-critical failures (Sheets, email) log warnings and continue.
# ─────────────────────────────────────────────────────────────────────────────
def run_workflow():
    """Execute the full daily LinkedIn automation workflow.

    Steps: duplicate check → research → generate post → quality gate →
    generate image → upload image → publish → log to Sheets → notify via email.
    """
    log.info("=" * 50)
    log.info("▶ Starting LinkedIn automation workflow")

    # ── Select today's topic ──────────────────────────────────────────────────
    today     = datetime.now().strftime("%Y-%m-%d")
    day_index = datetime.now().timetuple().tm_yday % len(TOPICS)
    topic_data = TOPICS[day_index]

    topic    = topic_data["topic"]
    company  = topic_data["company"]
    hashtags = topic_data["hashtags"]

    log.info(f"📅 Today: {today} | Topic: {company}")

    # ── Duplicate check ───────────────────────────────────────────────────────
    if is_duplicate(today):
        log.info("⏭️  Already posted today — skipping workflow.")
        send_email(
            subject=f"[LinkedIn Bot] Skipped — Already posted today ({today})",
            body=(
                f"The LinkedIn automation skipped today's run.\n\n"
                f"Reason: A post for {today} already exists in Google Sheets.\n"
                f"Company: {company}\n"
                f"Topic: {topic}\n\n"
                f"No action needed."
            )
        )
        return

    try:
        # ── Step 1: Research ──────────────────────────────────────────────────
        research = research_topic(topic, company)

        # ── Step 2: Generate post with quality retry loop ─────────────────────
        post_text = None
        quality   = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            log.info(f"✍️  Generating post (attempt {attempt}/{config.MAX_RETRIES})")
            post_text = generate_post(research, topic, company, hashtags)
            quality   = quality_check(post_text)
            log.info(f"📊 Quality score: {quality['score']}/10 — {quality['reason']}")

            if quality["approved"]:
                break
            log.warning(
                f"⚠️ Score {quality['score']}/10 is below minimum "
                f"{config.QUALITY_MIN_SCORE}. Retrying..."
            )

        # ── Step 3: Halt if quality gate failed after all retries ─────────────
        if not quality["approved"]:
            log.error(
                f"❌ Post quality too low after {config.MAX_RETRIES} attempts. "
                f"Final score: {quality['score']}/10"
            )
            send_email(
                subject=f"[LinkedIn Bot] ⚠️ Quality gate failed — {company} ({today})",
                body=(
                    f"The LinkedIn automation could not publish today's post.\n\n"
                    f"Reason: Post quality score too low after {config.MAX_RETRIES} attempts.\n"
                    f"Date:    {today}\n"
                    f"Company: {company}\n"
                    f"Final Score: {quality['score']}/10 (minimum: {config.QUALITY_MIN_SCORE})\n"
                    f"Reason: {quality.get('reason', 'N/A')}\n\n"
                    f"Action: You may want to run the script manually or adjust the prompt."
                )
            )
            log_to_sheet(today, topic, company, post_text, "", quality["score"], "QUALITY_FAILED")
            return

        # ── Step 4: Generate image ────────────────────────────────────────────
        image_bytes, image_url = generate_image(company, topic)

        # ── Step 5: Upload image to LinkedIn ──────────────────────────────────
        image_asset = linkedin_upload_image(image_bytes)

        # ── Step 6: Publish post to LinkedIn ──────────────────────────────────
        linkedin_post(post_text, image_asset)

        # ── Step 7: Log success to Google Sheets ──────────────────────────────
        log_to_sheet(today, topic, company, post_text, image_url, quality["score"], "SUCCESS")

        # ── Step 8: Send success email notification ─────────────────────────────────
        preview = post_text[:300] + "..." if len(post_text) > 300 else post_text
        send_email(
            subject=f"[LinkedIn Bot] ✅ Post published — {company} ({today})",
            body=(
                f"Your LinkedIn post was published successfully!\n\n"
                f"Date:    {today}\n"
                f"Company: {company}\n"
                f"Topic:   {topic}\n"
                f"Quality: {quality['score']}/10\n\n"
                f"--- POST PREVIEW ---\n\n"
                f"{preview}\n\n"
                f"--- END PREVIEW ---\n\n"
                f"Check your LinkedIn profile to see the full post."
            )
        )

        log.info("✅ Workflow complete")

    except requests.exceptions.HTTPError as e:
        err_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        log.error(f"❌ Workflow failed (HTTP error): {err_msg}")
        send_email(
            subject=f"[LinkedIn Bot] ❌ ERROR — HTTP error ({today})",
            body=(
                f"The LinkedIn automation failed with an HTTP error.\n\n"
                f"Date:    {today}\n"
                f"Company: {company}\n"
                f"Error:   {err_msg}\n\n"
                f"Check logs/automation.log for full details."
            )
        )
        log_to_sheet(today, topic, company, "", "", 0, f"ERROR: {err_msg}")

    except requests.exceptions.Timeout as e:
        log.error(f"❌ Workflow failed (timeout): {e}")
        send_email(
            subject=f"[LinkedIn Bot] ❌ ERROR — Request timeout ({today})",
            body=(
                f"The LinkedIn automation failed due to a request timeout.\n\n"
                f"Date:    {today}\n"
                f"Company: {company}\n"
                f"Error:   {str(e)}\n\n"
                f"Check logs/automation.log for full details."
            )
        )
        log_to_sheet(today, topic, company, "", "", 0, f"ERROR: Timeout - {e}")

    except Exception as e:
        log.error(f"❌ Workflow failed (unexpected): {e}")
        send_email(
            subject=f"[LinkedIn Bot] ❌ ERROR — Workflow crashed ({today})",
            body=(
                f"The LinkedIn automation encountered an unexpected error.\n\n"
                f"Date:    {today}\n"
                f"Company: {company}\n"
                f"Error:   {str(e)}\n\n"
                f"Check logs/automation.log for the full traceback.\n"
                f"Action: Fix the issue and re-run manually if needed."
            )
        )
        log_to_sheet(today, topic, company, "", "", 0, f"ERROR: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULER ENTRY POINT
# Runs the workflow every day at the time defined in config.POST_TIME.
#
# To TEST IMMEDIATELY without waiting for the scheduled time:
#   Uncomment the run_workflow() line below, run the script, then re-comment it.
#   ⚠️ Do NOT commit with run_workflow() uncommented.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"🕙 Scheduler started — will post daily at {config.POST_TIME}")
    schedule.every().day.at(config.POST_TIME).do(run_workflow)

    # ── Uncomment ONLY for immediate testing, then re-comment before committing ──
    # run_workflow()

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every 60 seconds (not 1 second — avoids wasting CPU)
