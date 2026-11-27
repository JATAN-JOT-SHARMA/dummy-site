import os
import io
import uuid
import boto3
from datetime import datetime, timezone
from functools import wraps
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-" + os.urandom(16).hex())

# ---------------- DATABASE ----------------
db_url = os.getenv("DATABASE_URL", "").strip()
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if not db_url:
    db_url = "sqlite:///portfolio.db"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db = SQLAlchemy(app)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# ---------------- S3 (lazy-safe) ----------------
S3_ERROR = None
try:
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_ENDPOINT_URL_S3") or None,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-2"),
        config=Config(signature_version="s3v4"),
    )
except Exception as e:
    s3 = None
    S3_ERROR = str(e)

BUCKET = os.getenv("NEON_S3_BUCKET", "s3-bucket-1232")


# ---------------- FONTS ----------------
FONT_CHOICES = {
    "Inter":             [400, 500, 600, 700, 800],
    "Roboto":            [400, 500, 700],
    "Poppins":           [400, 500, 600, 700, 800],
    "Montserrat":        [400, 500, 600, 700, 800],
    "Playfair Display":  [400, 500, 600, 700, 800],
    "Fira Code":         [400, 500, 600, 700],
    "Lora":              [400, 500, 600, 700],
    "Merriweather":      [400, 700, 900],
    "Source Sans 3":     [400, 500, 600, 700],
    "Source Serif 4":    [400, 500, 600, 700],
    "Nunito":            [400, 600, 700, 800],
    "Nunito Sans":       [400, 600, 700, 800],
    "Raleway":           [400, 500, 600, 700, 800],
    "Work Sans":         [400, 500, 600, 700],
    "DM Sans":           [400, 500, 700],
    "DM Serif Display":  [400],
    "Manrope":           [400, 500, 600, 700, 800],
    "Space Grotesk":     [400, 500, 600, 700],
    "Sora":              [400, 500, 600, 700, 800],
    "Outfit":            [400, 500, 600, 700, 800],
    "Plus Jakarta Sans": [400, 500, 600, 700, 800],
    "IBM Plex Sans":     [400, 500, 600, 700],
    "IBM Plex Mono":     [400, 500, 600, 700],
    "JetBrains Mono":    [400, 500, 600, 700, 800],
    "Oswald":            [400, 500, 600, 700],
    "Bebas Neue":        [400],
    "Anton":             [400],
    "Archivo":           [400, 500, 600, 700, 800],
    "Barlow":            [400, 500, 600, 700, 800],
    "Cabin":             [400, 500, 600, 700],
    "Cormorant Garamond":[400, 500, 600, 700],
    "Crimson Text":      [400, 600, 700],
    "EB Garamond":       [400, 500, 600, 700, 800],
    "Exo 2":             [400, 500, 600, 700, 800],
    "Figtree":           [400, 500, 600, 700, 800],
    "Heebo":             [400, 500, 600, 700, 800],
    "Josefin Sans":      [400, 500, 600, 700],
    "Karla":             [400, 500, 600, 700, 800],
    "Kanit":             [400, 500, 600, 700],
    "Libre Baskerville": [400, 700],
    "Libre Franklin":    [400, 500, 600, 700, 800],
    "Lato":              [400, 700, 900],
    "Mulish":            [400, 500, 600, 700, 800],
    "Open Sans":         [400, 500, 600, 700, 800],
    "PT Sans":           [400, 700],
    "PT Serif":          [400, 700],
    "Quicksand":         [400, 500, 600, 700],
    "Rubik":             [400, 500, 600, 700, 800],
    "Titillium Web":     [400, 600, 700, 900],
    "Ubuntu":            [400, 500, 700],
    "Urbanist":          [400, 500, 600, 700, 800],
    "Varela Round":      [400],
    "Zilla Slab":        [400, 500, 600, 700],
}
DEFAULT_FONT = "Inter"


# ---------------- MODELS ----------------
class ContactMessage(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SiteContent(db.Model):
    __tablename__ = "site_content"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, default="")


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    summary = db.Column(db.String(300))
    body = db.Column(db.Text, nullable=False)
    tech_stack = db.Column(db.String(300))
    file_url = db.Column(db.Text)
    media_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------- DEFAULTS ----------------
with app.app_context():
    db.create_all()
    defaults = {
        "theme_bg": "#111111",
        "theme_text": "#ffffff",
        "theme_accent": "#65a30d",
        "theme_accent_hover": "#4d7c0f",
        "font_family": DEFAULT_FONT,
        "font_size_base": "16px",
        "font_size_heading": "3.5rem",
        "logo_text": "Your Logo",
        "nav_home": "Home",
        "nav_about": "about me",
        "nav_recent_work": "recent work",
        "nav_contact": "Get in Touch",
        "nav_login_text": "Login",
        "hero_title": "Your Name Here",
        "hero_bio": "Intro text: I build fast, clean web apps with Python, Flask and modern front-ends. I care about performance, clean code, and great user experiences.",
        "hero_image": "",
        "cta_text": "Let's get started ->",
        "worked_with_title": "Worked with",
        "worked_with_logos": "CloudPix, Dropbox, PAYCHEX, plastic, stripe",
        "work_title": "Recent Work",
        "contact_title": "Get in Touch",
        "contact_btn_text": "Send Message",
        "about_content": "I am a passionate full-stack developer with a strong focus on building scalable backend systems and smooth front-end experiences. Over the years, I have worked with startups and established companies to bring their digital products to life.",
        "social_linkedin": "https://linkedin.com/in/yourname",
        "social_github": "https://github.com/yourname",
        "footer_text": "All rights reserved.",
    }
    for k, v in defaults.items():
        if not SiteContent.query.filter_by(key=k).first():
            db.session.add(SiteContent(key=k, value=v))
    db.session.commit()


# ---------------- HELPERS ----------------
def is_admin():
    return session.get("admin") is True


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not is_admin():
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return f(*a, **kw)
    return wrapper


def get_content():
    return {c.key: c.value for c in SiteContent.query.all()}


def build_font_url(font):
    if font not in FONT_CHOICES:
        font = DEFAULT_FONT
    weights = FONT_CHOICES[font]
    weight_q = ";".join(str(w) for w in weights)
    font_q = font.replace(" ", "+")
    return f"https://fonts.googleapis.com/css2?family={font_q}:wght@{weight_q}&display=swap"


def get_theme_css(content):
    font = content.get("font_family", DEFAULT_FONT) or DEFAULT_FONT
    font_url = build_font_url(font)

    bg = content.get("theme_bg", "#111111")
    text = content.get("theme_text", "#ffffff")
    accent = content.get("theme_accent", "#65a30d")
    accent_hover = content.get("theme_accent_hover", "#4d7c0f")
    fs_base = content.get("font_size_base", "16px")
    fs_heading = content.get("font_size_heading", "3.5rem")

    accent_rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    accent_rgba = f"rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 0.1)"

    return f"""
    <style>
      @import url('{font_url}');
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html {{ scroll-behavior: smooth; }}
      body {{
        font-family: '{font}', sans-serif;
        background: {bg};
        color: {text};
        line-height: 1.6;
        font-size: {fs_base};
        -webkit-font-smoothing: antialiased;
      }}
      a {{ text-decoration: none; color: inherit; transition: 0.3s; }}
      .container {{ max-width: 1100px; margin: 0 auto; padding: 0 20px; }}

      header {{ padding: 24px 0; border-bottom: 1px solid rgba(255,255,255,0.05); position: sticky; top: 0; background: {bg}; z-index: 100; }}
      .nav-wrapper {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }}
      .logo-text {{ font-size: 1.5rem; font-weight: 800; color: {text}; letter-spacing: -0.5px; margin-right: 20px; }}
      .nav-links {{ display: flex; gap: 30px; list-style: none; align-items: center; flex-wrap: wrap; }}
      .nav-links a {{ font-size: 0.95rem; font-weight: 500; color: #a1a1aa; }}
      .nav-links a:hover {{ color: {text}; }}
      .nav-login {{ background: {accent_rgba}; color: {accent} !important; padding: 6px 16px; border-radius: 6px; font-weight: 600; border: 1px solid {accent_rgba}; }}
      .nav-login:hover {{ background: {accent}; color: #fff !important; }}
      .social-nav {{ display: flex; gap: 15px; color: #a1a1aa; align-items: center; flex-wrap: wrap; }}
      .social-nav a:hover {{ color: {text}; }}

      .hero {{ padding: 100px 0 60px; }}
      .hero-grid {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 60px; align-items: center; }}
      .hero-text h1 {{ font-size: {fs_heading}; font-weight: 800; margin-bottom: 20px; line-height: 1.2; color: {text}; }}
      .hero-text p {{ font-size: 1.1rem; color: #a1a1aa; margin-bottom: 40px; max-width: 500px; }}
      .btn-green {{ display: inline-flex; align-items: center; justify-content: center; background: {accent}; color: #fff; padding: 16px 32px; border-radius: 6px; font-weight: 600; font-size: 1rem; border: none; cursor: pointer; transition: 0.2s; }}
      .btn-green:hover {{ background: {accent_hover}; transform: translateY(-2px); }}
      .hero-image {{ display: flex; justify-content: flex-end; }}
      .hero-image img {{ width: 380px; height: 380px; object-fit: cover; border-radius: 50%; border: 4px solid rgba(255,255,255,0.05); }}
      .hero-image .placeholder {{ width: 380px; height: 380px; border-radius: 50%; border: 4px dashed rgba(255,255,255,0.15); display: flex; align-items: center; justify-content: center; color: #a1a1aa; font-size: 0.9rem; text-align: center; padding: 20px; }}

      .worked-with {{ margin-top: 80px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 40px; }}
      .worked-with p {{ font-size: 0.85rem; color: #a1a1aa; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 20px; }}
      .logo-strip {{ display: flex; gap: 40px; align-items: center; flex-wrap: wrap; opacity: 0.4; filter: grayscale(100%); }}
      .logo-strip span {{ font-size: 1.2rem; font-weight: 700; color: {text}; font-style: italic; }}

      .section {{ padding: 80px 0; border-top: 1px solid rgba(255,255,255,0.05); }}
      .section-title {{ font-size: 2rem; font-weight: 700; margin-bottom: 40px; color: {text}; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 30px; }}
      .card {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 30px; transition: 0.3s; display: flex; flex-direction: column; }}
      .card:hover {{ transform: translateY(-5px); border-color: {accent}; }}
      .card h3 {{ font-size: 1.4rem; margin-bottom: 12px; color: {text}; }}
      .card p {{ color: #a1a1aa; font-size: 0.95rem; margin-bottom: 20px; flex-grow: 1; }}
      .tech-tag {{ display: inline-block; background: {accent_rgba}; color: {accent}; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; margin-right: 10px; margin-bottom: 10px; }}
      .download-btn {{ display: inline-block; background: rgba(255,255,255,0.1); color: {text}; padding: 8px 16px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; margin-top: 15px; text-align: center; }}
      .download-btn:hover {{ background: rgba(255,255,255,0.2); }}

      .contact-form {{ max-width: 600px; }}
      .form-group {{ margin-bottom: 20px; }}
      .form-group label {{ display: block; margin-bottom: 8px; font-size: 0.9rem; color: #a1a1aa; }}
      input, textarea {{ width: 100%; padding: 16px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; color: {text}; font-family: inherit; font-size: 1rem; outline: none; }}
      input:focus, textarea:focus {{ border-color: {accent}; }}
      textarea {{ resize: vertical; min-height: 150px; }}

      footer {{ padding: 40px 0; text-align: center; border-top: 1px solid rgba(255,255,255,0.05); color: #a1a1aa; font-size: 0.9rem; display: flex; justify-content: space-between; align-items: center; }}
      footer a {{ color: {accent}; font-weight: 600; }}

      @media (max-width: 768px) {{
        .hero-grid {{ grid-template-columns: 1fr; text-align: center; gap: 40px; }}
        .hero-text h1 {{ font-size: 2.5rem; }}
        .hero-text p {{ margin: 0 auto 30px; }}
        .hero-image {{ justify-content: center; }}
        .hero-image img {{ width: 280px; height: 280px; }}
        .hero-image .placeholder {{ width: 280px; height: 280px; }}
        .nav-wrapper {{ flex-direction: column; justify-content: center; }}
        .logo-text {{ margin-right: 0; margin-bottom: 10px; }}
        .nav-links {{ justify-content: center; gap: 15px; }}
        .social-nav {{ justify-content: center; margin-top: 10px; width: 100%; }}
        .logo-strip {{ justify-content: center; gap: 20px; }}
        footer {{ flex-direction: column; gap: 15px; }}
      }}
    </style>
    """


def get_navbar(content):
    return f"""
    <header>
      <div class="container nav-wrapper">
        <div style="display:flex; align-items:center;">
          <div class="logo-text">{content.get('logo_text', 'Logo')}</div>
        </div>
        <ul class="nav-links">
          <li><a href="/#home">{content.get('nav_home', 'Home')}</a></li>
          <li><a href="/#about">{content.get('nav_about', 'about me')}</a></li>
          <li><a href="/#work">{content.get('nav_recent_work', 'recent work')}</a></li>
          <li><a href="/#contact">{content.get('nav_contact', 'Get in Touch')}</a></li>
        </ul>
        <div class="social-nav">
          <a href="{content.get('social_linkedin', '#')}" target="_blank">LinkedIn</a>
          <a href="{content.get('social_github', '#')}" target="_blank">GitHub</a>
          <a href="/login" class="nav-login">{content.get('nav_login_text', 'Login')}</a>
        </div>
      </div>
    </header>
    """


def get_footer(content):
    year = datetime.now(timezone.utc).year
    return f"""
    <footer>
      <div class="container" style="display: flex; justify-content: space-between; width: 100%; align-items:center;">
        <div>&copy; {year} {content.get('hero_title', '')}. {content.get('footer_text', 'All rights reserved.')}</div>
        <div><a href="/login" style="color:#a1a1aa; font-size:0.85rem; font-weight:500;">Admin Panel</a></div>
      </div>
    </footer>
    """


def hero_image_html(content):
    url = (content.get("hero_image") or "").strip()
    if url:
        return f'<img src="{url}" alt="Profile Photo">'
    return '<div class="placeholder">No profile image yet.<br>Upload one from the Admin Panel.</div>'


# ---------------- PUBLIC ROUTES ----------------
@app.route("/")
def home():
    content = get_content()
    projects = Project.query.order_by(Project.created_at.desc()).all()
    theme_css = get_theme_css(content)
    navbar = get_navbar(content)
    footer = get_footer(content)
    accent = content.get("theme_accent", "#65a30d")
    contact_btn = content.get("contact_btn_text", "Send Message")
    hero_img = hero_image_html(content)

    cards = "".join([
        f"""
        <div class="card">
          <h3><a href="/project/{p.slug}" style="color:inherit;">{p.title}</a></h3>
          <p>{(p.summary or p.body[:120])}...</p>
          <div><span class="tech-tag">{p.tech_stack or 'Project'}</span></div>
          <a href="/project/{p.slug}" class="download-btn" style="margin-top:auto;">View Details</a>
        </div>
        """ for p in projects
    ]) or '<p style="color:#a1a1aa;">No projects yet.</p>'

    logos_html = "".join([
        f"<span>{logo.strip()}</span>"
        for logo in content.get("worked_with_logos", "").split(",") if logo.strip()
    ])

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{content.get('hero_title')} | Portfolio</title>
      {theme_css}
    </head>
    <body>
      {navbar}

      <section id="home" class="hero">
        <div class="container">
          <div class="hero-grid">
            <div class="hero-text">
              <h1>{content.get('hero_title', 'Your Name Here')}</h1>
              <p>{content.get('hero_bio', 'Intro text...')}</p>
              <a href="#contact" class="btn-green">{content.get('cta_text', 'See my work')}</a>
            </div>
            <div class="hero-image">
              {hero_img}
            </div>
          </div>
          <div class="worked-with">
            <p>{content.get('worked_with_title', 'Worked with')}</p>
            <div class="logo-strip">{logos_html}</div>
          </div>
        </div>
      </section>

      <section id="about" class="section">
        <div class="container">
          <h2 class="section-title">About Me</h2>
          <div style="max-width: 800px;">
            <p style="font-size: 1.1rem; color: #a1a1aa; line-height: 1.8; white-space: pre-wrap;">{content.get('about_content', 'Bio coming soon...')}</p>
          </div>
        </div>
      </section>

      <section id="work" class="section">
        <div class="container">
          <h2 class="section-title">{content.get('work_title', 'Recent Work')}</h2>
          <div class="grid">{cards}</div>
        </div>
      </section>

      <section id="contact" class="section">
        <div class="container">
          <h2 class="section-title">{content.get('contact_title', 'Get in Touch')}</h2>
          <div class="contact-form">
            <form id="contactForm">
              <div class="form-group"><label>Name</label><input type="text" name="name" required></div>
              <div class="form-group"><label>Email</label><input type="email" name="email" required></div>
              <div class="form-group"><label>Message</label><textarea name="message" required></textarea></div>
              <button type="submit" class="btn-green" id="submitBtn" style="width: 100%;">{contact_btn}</button>
              <div id="msg" style="margin-top:15px; font-weight:600;"></div>
            </form>
          </div>
        </div>
      </section>

      {footer}

      <script>
        document.getElementById('contactForm').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const btn = document.getElementById('submitBtn');
          const msg = document.getElementById('msg');
          btn.disabled = true; btn.textContent = 'Sending...';
          try {{
            const res = await fetch('/submit', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(Object.fromEntries(new FormData(e.target)))
            }});
            const data = await res.json();
            msg.style.color = data.ok ? '{accent}' : '#ef4444';
            msg.textContent = data.ok ? 'Thanks! I will contact you soon.' : (data.error || 'Failed.');
            if (data.ok) e.target.reset();
          }} catch {{ msg.textContent = 'Network error.'; msg.style.color = '#ef4444'; }}
          finally {{ btn.disabled = false; btn.textContent = {contact_btn!r}; }}
        }});
      </script>
    </body>
    </html>
    """
    return html


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()
    if not (name and email and message):
        return jsonify({"ok": False, "error": "All fields are required."}), 400
    db.session.add(ContactMessage(name=name, email=email, message=message))
    db.session.commit()
    return jsonify({"ok": True})


# ---------------- AUTH ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("email") == "admin"
                and request.form.get("password") == ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin"))
        return "Invalid credentials. <a href='/login'>Try again</a>", 401

    content = get_content()
    theme_css = get_theme_css(content)
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin Login</title>{theme_css}</head>
    <body style="display:flex;justify-content:center;align-items:center;height:100vh;">
      <form method="POST" style="background: rgba(255,255,255,0.05); padding:40px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); width:320px;">
        <h2 style="margin-bottom:20px;text-align:center;">Admin Login</h2>
        <input type="text" name="email" placeholder="Username (admin)" required style="margin-bottom:15px;">
        <input type="password" name="password" placeholder="Password" required style="margin-bottom:20px;">
        <button type="submit" class="btn-green" style="width:100%;">Login</button>
        <p style="text-align:center; margin-top:15px;"><a href="/" style="color:#a1a1aa; font-size:0.9rem;">Back to Home</a></p>
      </form>
    </body></html>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin")
def admin():
    if not is_admin():
        return redirect(url_for("login"))

    content = get_content()
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    projects = Project.query.order_by(Project.created_at.desc()).all()

    admin_css = """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body { font-family: 'Inter', sans-serif; background: #111; color: #fff; line-height: 1.6; }
      a { text-decoration: none; color: inherit; }
      .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
      .btn-green { display: inline-flex; align-items: center; justify-content: center; background: #65a30d; color: #fff; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 1rem; border: none; cursor: pointer; transition: 0.2s; }
      .btn-green:hover { background: #4d7c0f; }
      .admin-card { background: rgba(255,255,255,0.05); padding: 30px; border-radius: 12px; margin-bottom: 30px; border: 1px solid rgba(255,255,255,0.1); }
      .admin-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
      label { display: block; margin-bottom: 5px; color: #a1a1aa; font-size: 0.9rem; font-weight: 600; }
      .admin-card h3 { color: #65a30d; margin-bottom: 15px; font-size: 1.1rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; }
      table { width: 100%; border-collapse: collapse; margin-top: 20px; }
      th, td { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 0.9rem; vertical-align: top; }
      th { color: #a1a1aa; font-weight: 500; }
      input, textarea, select { width: 100%; padding: 12px 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; color: #fff; font-family: inherit; font-size: 1rem; outline: none; }
      input:focus, textarea:focus, select:focus { border-color: #65a30d; }
      input[type="color"] { padding: 5px; height: 50px; cursor: pointer; }
      input[type="file"] { padding: 10px; cursor: pointer; }
      .file-drop { border: 2px dashed rgba(255,255,255,0.2); border-radius: 10px; padding: 20px; text-align: center; transition: 0.2s; cursor: pointer; }
      .file-drop:hover { border-color: #65a30d; background: rgba(101,163,13,0.05); }
      .file-drop.has-file { border-color: #65a30d; border-style: solid; }
      @media (max-width: 700px) { .admin-grid { grid-template-columns: 1fr; } }
    </style>
    """

    current_font = content.get("font_family", DEFAULT_FONT)
    font_options = "".join(
        f'<option value="{name}"{" selected" if current_font == name else ""}>'
        f'{name}{" (Default)" if name == DEFAULT_FONT else ""}</option>'
        for name in FONT_CHOICES
    )

    current_hero = (content.get("hero_image") or "").strip()
    if current_hero:
        hero_preview = f'<img id="hero_image_preview" src="{current_hero}" alt="Preview" style="width:100%; height:100%; object-fit:cover;">'
        hero_has_file = " has-file"
        hero_filename = "Current image loaded"
    else:
        hero_preview = '<div id="hero_image_preview" style="width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:#666; font-size:0.8rem; text-align:center; padding:10px;">No image</div>'
        hero_has_file = ""
        hero_filename = "No file selected"

    projects_rows = "".join([
        f"""
        <tr id="proj-{p.id}">
          <td>{p.title}</td>
          <td>{p.slug}</td>
          <td>{p.tech_stack or '-'}</td>
          <td>{p.created_at.strftime('%Y-%m-%d') if p.created_at else '-'}</td>
          <td><button onclick="deleteProject({p.id})" style="background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:0.8rem;">Delete</button></td>
        </tr>
        """ for p in projects
    ])
    messages_rows = "".join([
        f"""
        <tr id="msg-{m.id}">
          <td>{m.name}</td>
          <td><a href="mailto:{m.email}" style="color:#65a30d;">{m.email}</a></td>
          <td style="max-width:400px; white-space:pre-wrap;">{m.message}</td>
          <td>{m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '-'}</td>
          <td><button onclick="deleteMessage({m.id})" style="background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:0.8rem;">Delete</button></td>
        </tr>
        """ for m in messages
    ])

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Admin Dashboard</title>{admin_css}</head>
    <body>
      <div class="container" style="padding-top: 40px; padding-bottom: 60px;">
        <div style="display:flex; justify-content:space-between; margin-bottom: 40px; align-items: center; flex-wrap: wrap; gap: 10px;">
          <h1>Admin Panel</h1>
          <div>
            <a href="/" class="btn-green" style="padding: 10px 20px; font-size: 0.9rem;">View Site</a>
            <a href="/logout" class="btn-green" style="padding: 10px 20px; font-size: 0.9rem; background: #ef4444;">Logout</a>
          </div>
        </div>

        <div class="admin-card">
          <h3>🎨 Theme & Appearance</h3>
          <div class="admin-grid">
            <div><label>Background Color</label><input type="color" id="theme_bg" value="{content.get('theme_bg', '#111111')}"></div>
            <div><label>Text Color</label><input type="color" id="theme_text" value="{content.get('theme_text', '#ffffff')}"></div>
            <div><label>Accent Color</label><input type="color" id="theme_accent" value="{content.get('theme_accent', '#65a30d')}"></div>
            <div><label>Accent Hover Color</label><input type="color" id="theme_accent_hover" value="{content.get('theme_accent_hover', '#4d7c0f')}"></div>
            <div>
              <label>Font Family</label>
              <select id="font_family">{font_options}</select>
            </div>
            <div><label>Base Font Size</label><input id="font_size_base" value="{content.get('font_size_base', '16px')}"></div>
            <div><label>Heading Font Size</label><input id="font_size_heading" value="{content.get('font_size_heading', '3.5rem')}"></div>
          </div>
        </div>

        <div class="admin-card">
          <h3>Navbar & Hero Section</h3>
          <div class="admin-grid">
            <div><label>Logo Text</label><input id="logo_text" value="{content.get('logo_text', '')}"></div>
            <div><label>Nav Link 1</label><input id="nav_home" value="{content.get('nav_home', '')}"></div>
            <div><label>Nav Link 2</label><input id="nav_about" value="{content.get('nav_about', '')}"></div>
            <div><label>Nav Link 3</label><input id="nav_recent_work" value="{content.get('nav_recent_work', '')}"></div>
            <div><label>Nav Link 4</label><input id="nav_contact" value="{content.get('nav_contact', '')}"></div>
            <div><label>Nav Login Button Text</label><input id="nav_login_text" value="{content.get('nav_login_text', 'Login')}"></div>
            <div style="grid-column: span 2; border-top: 1px dashed rgba(255,255,255,0.1); margin: 10px 0;"></div>
            <div><label>Hero Title</label><input id="hero_title" value="{content.get('hero_title', '')}"></div>
            <div><label>CTA Button Text</label><input id="cta_text" value="{content.get('cta_text', '')}"></div>
            <div><label>LinkedIn URL</label><input id="social_linkedin" value="{content.get('social_linkedin', '')}"></div>
            <div><label>GitHub URL</label><input id="social_github" value="{content.get('social_github', '')}"></div>
          </div>

          <div style="margin-top:20px;">
            <label>Hero Profile Image (Upload)</label>
            <div style="display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap;">
              <div style="flex:1; min-width:280px;">
                <div id="heroDrop" class="file-drop{hero_has_file}" onclick="document.getElementById('hero_image_file').click();">
                  <div style="font-size:1.6rem; margin-bottom:6px;">📷</div>
                  <div id="heroFileName" style="font-size:0.9rem; color:#ccc;">{hero_filename}</div>
                  <div style="font-size:0.75rem; color:#777; margin-top:6px;">Click to choose PNG / JPG / WEBP / GIF / SVG (max 16MB)</div>
                </div>
                <input type="file" id="hero_image_file" accept="image/png,image/jpeg,image/jpg,image/gif,image/webp,image/svg+xml" style="display:none;">
                <button type="button" class="btn-green" onclick="uploadHeroImage()" id="heroUploadBtn" style="margin-top:12px; padding:10px 20px; font-size:0.9rem; width:100%;">Upload Image</button>
                <div id="heroUploadMsg" style="margin-top:8px; font-size:0.85rem;"></div>
              </div>
              <div style="width:160px; height:160px; border-radius:50%; overflow:hidden; border:2px solid rgba(255,255,255,0.15); flex-shrink:0; background:#000;">
                {hero_preview}
              </div>
            </div>
          </div>

          <label style="margin-top:20px;">Hero Bio (Short Intro)</label>
          <textarea id="hero_bio" rows="3">{content.get('hero_bio', '')}</textarea>
        </div>

        <div class="admin-card">
          <h3>Logos & Section Titles</h3>
          <div class="admin-grid">
            <div><label>Worked With Title</label><input id="worked_with_title" value="{content.get('worked_with_title', '')}"></div>
            <div><label>Logos (Comma separated)</label><input id="worked_with_logos" value="{content.get('worked_with_logos', '')}"></div>
            <div><label>Work Section Title</label><input id="work_title" value="{content.get('work_title', '')}"></div>
            <div><label>Contact Section Title</label><input id="contact_title" value="{content.get('contact_title', '')}"></div>
            <div><label>Contact Button Text</label><input id="contact_btn_text" value="{content.get('contact_btn_text', '')}"></div>
            <div><label>Footer Copyright Text</label><input id="footer_text" value="{content.get('footer_text', '')}"></div>
          </div>
        </div>

        <div class="admin-card">
          <h3>About Me Section Content</h3>
          <label>Full Bio</label>
          <textarea id="about_content" rows="6">{content.get('about_content', '')}</textarea>
        </div>

        <button class="btn-green" onclick="saveContent()" style="margin-bottom: 30px; width: 100%;">Save All Content & Theme</button>

        <div class="admin-card">
          <h3>Projects Manager & File Upload</h3>
          <div class="admin-grid">
            <div><label>Project Title</label><input id="p_title" placeholder="e.g. E-Commerce App"></div>
            <div><label>URL Slug (no spaces)</label><input id="p_slug" placeholder="e.g. ecommerce-app"></div>
            <div><label>Tech Stack</label><input id="p_tech" placeholder="e.g. Python, Flask, AWS"></div>
            <div><label>Short Summary</label><input id="p_summary" placeholder="A brief description..."></div>
          </div>
          <div style="margin-top:15px;">
            <label>Upload Project File (ZIP, PDF, etc - Max 16MB)</label>
            <input type="file" id="p_file" accept=".zip,.pdf,.png,.jpg,.jpeg,.gif,.webp,.mp4,.webm,.mov,.txt,.md,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.py,.js,.html,.css,.json,.csv,.7z,.rar">
          </div>
          <label style="margin-top:20px;">Full Project Description</label>
          <textarea id="p_body" rows="4" placeholder="Detailed project description..."></textarea>
          <button class="btn-green" onclick="addProject()" style="margin-top: 15px;">Add Project</button>
        </div>

        <div class="admin-card">
          <h3>Existing Projects</h3>
          <table>
            <thead><tr><th>Title</th><th>Slug</th><th>Tech</th><th>Created</th><th>Actions</th></tr></thead>
            <tbody id="projectList">{projects_rows}</tbody>
          </table>
          {'' if projects else '<p style="color:#a1a1aa; margin-top:15px;">No projects yet.</p>'}
        </div>

        <div class="admin-card">
          <h3>Contact Messages ({len(messages)})</h3>
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Message</th><th>Date</th><th>Actions</th></tr></thead>
            <tbody>{messages_rows}</tbody>
          </table>
          {'' if messages else '<p style="color:#a1a1aa; margin-top:15px;">No messages yet.</p>'}
        </div>
      </div>

      <script>
        async function saveContent() {{
          const fields = [
            'theme_bg','theme_text','theme_accent','theme_accent_hover','font_family',
            'font_size_base','font_size_heading','logo_text','nav_home','nav_about',
            'nav_recent_work','nav_contact','nav_login_text','hero_title',
            'cta_text','social_linkedin','social_github','hero_bio','worked_with_title',
            'worked_with_logos','work_title','contact_title','contact_btn_text',
            'footer_text','about_content'
          ];
          const data = {{}};
          fields.forEach(f => {{
            const el = document.getElementById(f);
            if (el) data[f] = el.value;
          }});
          try {{
            const res = await fetch('/admin/save', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(data)
            }});
            const result = await res.json();
            alert(result.ok ? 'Saved successfully!' : ('Error: ' + result.error));
            if (result.ok) location.reload();
          }} catch (e) {{ alert('Network error: ' + e.message); }}
        }}

        // Hero file picker UI
        const heroFileInput = document.getElementById('hero_image_file');
        const heroDrop = document.getElementById('heroDrop');
        const heroFileName = document.getElementById('heroFileName');
        if (heroFileInput) {{
          heroFileInput.addEventListener('change', () => {{
            if (heroFileInput.files.length > 0) {{
              const f = heroFileInput.files[0];
              heroFileName.textContent = f.name + ' (' + Math.round(f.size/1024) + ' KB)';
              heroDrop.classList.add('has-file');
            }}
          }});
        }}

        async function uploadHeroImage() {{
          const input = document.getElementById('hero_image_file');
          const msg = document.getElementById('heroUploadMsg');
          const btn = document.getElementById('heroUploadBtn');

          if (!input.files || input.files.length === 0) {{
            msg.style.color = '#ef4444';
            msg.textContent = 'Please choose an image file first.';
            return;
          }}
          const file = input.files[0];
          if (file.size > 1024 * 1024 * 1024) {{
            msg.style.color = '#ef4444';
            msg.textContent = 'File too large (max 1 GB).';
            return;
          }}

          const fd = new FormData();
          fd.append('file', file);

          btn.disabled = true;
          btn.textContent = 'Uploading...';
          msg.style.color = '#a1a1aa';
          msg.textContent = 'Uploading image...';

          try {{
            const res = await fetch('/admin/upload-hero', {{ method: 'POST', body: fd }});
            const data = await res.json();
            if (data.ok) {{
              msg.style.color = '#65a30d';
              msg.textContent = 'Uploaded successfully! Refreshing...';
              input.value = '';
              setTimeout(() => location.reload(), 700);
            }} else {{
              msg.style.color = '#ef4444';
              msg.textContent = 'Error: ' + (data.error || 'Unknown');
            }}
          }} catch (e) {{
            msg.style.color = '#ef4444';
            msg.textContent = 'Network error: ' + e.message;
          }} finally {{
            btn.disabled = false;
            btn.textContent = 'Upload Image';
          }}
        }}

        async function addProject() {{
          const title = document.getElementById('p_title').value.trim();
          const slug  = document.getElementById('p_slug').value.trim();
          const tech  = document.getElementById('p_tech').value.trim();
          const summary = document.getElementById('p_summary').value.trim();
          const body  = document.getElementById('p_body').value.trim();
          const fileInput = document.getElementById('p_file');
          const button = document.querySelector('button[onclick="addProject()"]');

          if (!title || !slug || !body) {{
            alert('Title, slug, and body are required.');
            return;
          }}

          if (fileInput.files.length > 0 && fileInput.files[0].size > 1024 * 1024 * 1024) {{
            alert('File too large (max 1 GB).');
            return;
          }}

          const formData = new FormData();
          formData.append('title', title);
          formData.append('slug', slug);
          formData.append('tech_stack', tech);
          formData.append('summary', summary);
          formData.append('body', body);
          if (fileInput.files.length > 0) {{
            formData.append('file', fileInput.files[0]);
          }}

          button.disabled = true;
          button.textContent = 'Uploading & Saving...';
          try {{
            const res = await fetch('/admin/projects', {{
              method: 'POST',
              body: formData
            }});
            const result = await res.json();
            if (result.ok) {{
              alert('Project and file uploaded successfully!');
              location.reload();
            }} else {{
              alert('Error: ' + (result.error || 'Unable to add project.'));
            }}
          }} catch (e) {{
            alert('Upload failed: ' + e.message);
          }} finally {{
            button.disabled = false;
            button.textContent = 'Add Project';
          }}
        }}

        async function deleteProject(id) {{
          if (!confirm('Delete this project?')) return;
          try {{
            const res = await fetch('/admin/projects/' + id, {{ method: 'DELETE' }});
            const result = await res.json();
            if (result.ok) {{
              const row = document.getElementById('proj-' + id);
              if (row) row.remove();
            }} else alert('Error: ' + result.error);
          }} catch (e) {{ alert('Network error: ' + e.message); }}
        }}

        async function deleteMessage(id) {{
          if (!confirm('Delete this message?')) return;
          try {{
            const res = await fetch('/admin/messages/' + id, {{ method: 'DELETE' }});
            const result = await res.json();
            if (result.ok) {{
              const row = document.getElementById('msg-' + id);
              if (row) row.remove();
            }} else alert('Error: ' + result.error);
          }} catch (e) {{ alert('Network error: ' + e.message); }}
        }}
      </script>
    </body>
    </html>
    """
    return html


# ---------------- PROJECT FILE STORAGE ----------------
PROJECT_ALLOWED_EXTENSIONS = {
    "zip", "pdf", "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mov", "txt", "md", "doc", "docx",
    "xls", "xlsx", "ppt", "pptx", "py", "js", "html",
    "css", "json", "csv", "7z", "rar"
}

def save_project_upload(upload):
    """Save a project file to S3, or to local static storage if S3 is unavailable."""
    if not upload or not upload.filename:
        return None

    original_name = secure_filename(upload.filename)
    if not original_name:
        raise ValueError("Invalid filename.")

    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in PROJECT_ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Allowed: ZIP, PDF, images, videos, "
            "Office documents, text and common source-code files."
        )

    content = upload.read()
    if not content:
        raise ValueError("The selected file is empty.")
    if len(content) > 1024 * 1024 * 1024:
        raise ValueError("File too large (maximum 1 GB).")

    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    content_type = upload.mimetype or "application/octet-stream"
    key = f"projects/{stored_name}"

    # Try S3 first. Do not require ACL because many modern S3 buckets disable ACLs.
    if s3 is not None:
        try:
            s3.upload_fileobj(
                io.BytesIO(content),
                BUCKET,
                key,
                ExtraArgs={"ContentType": content_type}
            )
            endpoint = (os.getenv("AWS_ENDPOINT_URL_S3") or "").rstrip("/")
            if endpoint:
                return f"{endpoint}/{BUCKET}/{key}"
            return f"https://{BUCKET}.s3.amazonaws.com/{key}"
        except Exception:
            # Local fallback keeps uploads working if S3 permissions/configuration fail.
            pass

    upload_dir = os.path.join(app.root_path, "static", "uploads", "projects")
    os.makedirs(upload_dir, exist_ok=True)
    local_path = os.path.join(upload_dir, stored_name)
    with open(local_path, "wb") as destination:
        destination.write(content)
    return f"/static/uploads/projects/{stored_name}"


# ---------------- ADMIN APIs ----------------
@app.route("/admin/save", methods=["POST"])
@admin_required
def admin_save():
    data = request.get_json(silent=True) or {}
    for key, value in data.items():
        row = SiteContent.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.session.add(SiteContent(key=key, value=value))
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/admin/presign", methods=["POST"])
@admin_required
def admin_presign():
    if s3 is None:
        return jsonify({"ok": False, "error": f"S3 not configured: {S3_ERROR}"}), 500
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    content_type = data.get("content_type") or "application/octet-stream"
    if not filename:
        return jsonify({"ok": False, "error": "Filename required"}), 400

    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-") or "file"
    key = f"projects/{uuid.uuid4().hex}_{safe_name}"

    try:
        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=3600,
        )
        endpoint = os.getenv("AWS_ENDPOINT_URL_S3", "")
        if endpoint:
            file_url = f"{endpoint.rstrip('/')}/{BUCKET}/{key}"
        else:
            file_url = f"https://{BUCKET}.s3.amazonaws.com/{key}"
        return jsonify({"ok": True, "upload_url": upload_url, "file_url": file_url})
    except (BotoCoreError, ClientError) as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/upload-hero", methods=["POST"])
@admin_required
def admin_upload_hero():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    allowed = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        return jsonify({"ok": False, "error": f"Unsupported image type: .{ext}"}), 400

    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-") or "profile"
    key = f"hero/{uuid.uuid4().hex}_{safe_name}"

    # Read file into memory so we don't get "I/O operation on closed file" if S3 fails
    file_bytes = file.read()

    # Try S3 first
    file_url = None
    s3_failed_error = None

    if s3 is not None:
        try:
            s3.upload_fileobj(
                io.BytesIO(file_bytes),
                BUCKET,
                key,
                ExtraArgs={"ContentType": file.content_type or f"image/{ext}", "ACL": "public-read"}
            )
            endpoint = os.getenv("AWS_ENDPOINT_URL_S3", "")
            if endpoint:
                file_url = f"{endpoint.rstrip('/')}/{BUCKET}/{key}"
            else:
                file_url = f"https://{BUCKET}.s3.amazonaws.com/{key}"
        except Exception as e:
            s3_failed_error = str(e)
    else:
        s3_failed_error = S3_ERROR or "S3 client not initialized"

    # Fallback to local storage if S3 failed
    if not file_url:
        try:
            upload_dir = os.path.join(app.root_path, "static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            local_name = key.split("/")[-1]
            local_path = os.path.join(upload_dir, local_name)
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            file_url = f"/static/uploads/{local_name}"
        except Exception as local_e:
            return jsonify({"ok": False, "error": f"S3 failed ({s3_failed_error}), and local fallback failed ({str(local_e)})"}), 500

    # Update DB
    try:
        row = SiteContent.query.filter_by(key="hero_image").first()
        if row:
            row.value = file_url
        else:
            db.session.add(SiteContent(key="hero_image", value=file_url))
        db.session.commit()
        return jsonify({"ok": True, "url": file_url})
    except Exception as db_e:
        return jsonify({"ok": False, "error": f"Database error: {str(db_e)}"}), 500


@app.route("/admin/projects", methods=["POST"])
@admin_required
def admin_create_project():
    # Supports both the new browser multipart upload and older JSON requests.
    data = request.form if request.form else (request.get_json(silent=True) or {})
    title = (data.get("title") or "").strip()
    slug = (data.get("slug") or "").strip()
    body = (data.get("body") or "").strip()

    if not (title and slug and body):
        return jsonify({"ok": False, "error": "Title, slug and body are required."}), 400
    if Project.query.filter_by(slug=slug).first():
        return jsonify({"ok": False, "error": "A project with that slug already exists."}), 400

    file_url = data.get("file_url") or None
    uploaded_file = request.files.get("file")
    if uploaded_file and uploaded_file.filename:
        try:
            file_url = save_project_upload(uploaded_file)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except Exception as error:
            app.logger.exception("Project file upload failed")
            return jsonify({"ok": False, "error": f"File upload failed: {error}"}), 500

    p = Project(
        title=title,
        slug=slug,
        summary=(data.get("summary") or "").strip(),
        body=body,
        tech_stack=(data.get("tech_stack") or "").strip(),
        file_url=file_url,
        media_url=data.get("media_url"),
    )
    try:
        db.session.add(p)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        app.logger.exception("Project save failed")
        return jsonify({"ok": False, "error": f"Could not save project: {error}"}), 500

    return jsonify({"ok": True, "id": p.id, "file_url": file_url})


@app.route("/admin/projects/<int:pid>", methods=["DELETE"])
@admin_required
def admin_delete_project(pid):
    p = db.session.get(Project, pid)
    if not p:
        return jsonify({"ok": False, "error": "Not found"}), 404
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/admin/messages/<int:mid>", methods=["DELETE"])
@admin_required
def admin_delete_message(mid):
    m = db.session.get(ContactMessage, mid)
    if not m:
        return jsonify({"ok": False, "error": "Not found"}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------- PUBLIC PROJECT DETAIL ----------------
@app.route("/project/<slug>")
def project_detail(slug):
    p = Project.query.filter_by(slug=slug).first()
    if not p:
        return "Project not found. <a href='/'>Back home</a>", 404

    content = get_content()
    theme_css = get_theme_css(content)
    navbar = get_navbar(content)
    footer = get_footer(content)
    accent = content.get("theme_accent", "#65a30d")

    tech = f'<p style="margin-top:30px;"><span class="tech-tag">{p.tech_stack}</span></p>' if p.tech_stack else ""
    file_preview = ""
    file_btn = ""
    if p.file_url:
        file_url = p.file_url
        file_ext = file_url.split("?", 1)[0].rsplit(".", 1)[-1].lower()
        if file_ext in {"png", "jpg", "jpeg", "gif", "webp"}:
            file_preview = (
                f'<div style="margin-top:30px;">'
                f'<h2 style="font-size:1.2rem;margin-bottom:12px;">Project Image</h2>'
                f'<img src="{file_url}" alt="{p.title}" '
                f'style="display:block;max-width:100%;max-height:650px;object-fit:contain;'
                f'border-radius:12px;border:1px solid rgba(255,255,255,.12);"></div>'
            )
        elif file_ext == "pdf":
            file_preview = (
                f'<div style="margin-top:30px;">'
                f'<h2 style="font-size:1.2rem;margin-bottom:12px;">Project Document</h2>'
                f'<iframe src="{file_url}" title="Project PDF" '
                f'style="width:100%;height:700px;border:1px solid rgba(255,255,255,.12);'
                f'border-radius:10px;background:#fff;"></iframe></div>'
            )
        elif file_ext in {"mp4", "webm", "mov"}:
            mime = "video/mp4" if file_ext in {"mp4", "mov"} else "video/webm"
            file_preview = (
                f'<div style="margin-top:30px;">'
                f'<h2 style="font-size:1.2rem;margin-bottom:12px;">Project Video</h2>'
                f'<video controls style="width:100%;max-height:650px;border-radius:12px;">'
                f'<source src="{file_url}" type="{mime}">'
                f'Your browser does not support video playback.</video></div>'
            )
        file_btn = (
            f'<p style="margin-top:20px;"><a href="{file_url}" target="_blank" '
            f'rel="noopener" class="btn-green" download>Download Project File</a></p>'
        )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{p.title} | Portfolio</title>{theme_css}</head>
    <body>
      {navbar}
      <section class="section">
        <div class="container">
          <p style="color:#a1a1aa; margin-bottom:10px;"><a href="/#work" style="color:{accent};">&larr; Back to Work</a></p>
          <h1 style="font-size:2.5rem; margin-bottom:15px;">{p.title}</h1>
          <p style="color:#a1a1aa; margin-bottom:30px;">{p.summary or ''}</p>
          <div style="white-space:pre-wrap; font-size:1.05rem; line-height:1.8;">{p.body}</div>
          {tech}
          {file_preview}
          {file_btn}
        </div>
      </section>
      {footer}
    </body></html>
    """


# ---------------- HEALTH ----------------
@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "time": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)