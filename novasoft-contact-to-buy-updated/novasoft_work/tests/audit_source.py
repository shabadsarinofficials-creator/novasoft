"""Dependency-free static audit for the contact-to-buy NovaSoft project."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "app.py").read_text(encoding="utf-8")
setup = (ROOT / "setup_wizard.py").read_text(encoding="utf-8")
product = (ROOT / "templates" / "product.html").read_text(encoding="utf-8")
home = (ROOT / "templates" / "home.html").read_text(encoding="utf-8")
admin = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
readme = (ROOT / "README.md").read_text(encoding="utf-8")
run_bat = (ROOT / "run.bat").read_text(encoding="utf-8")
ast.parse(source)
ast.parse(setup)
checks = {
    "Python source parses": True,
    "No Razorpay dependency": "razorpay" not in requirements,
    "No Razorpay client in app": "razorpay" not in source.lower(),
    "No checkout routes": "/checkout/" not in source,
    "Contact email is configured": "CONTACT_EMAIL" in setup and "contact_email" in source,
    "Contact phone is configured": "CONTACT_PHONE" in setup and "contact_phone" in source,
    "First admin setup is in browser": "admin_setup" in source and "admin_setup.html" in source,
    "Admin credentials are not read from environment": "ADMIN_USERNAME" not in source and "ADMIN_PASSWORD_HASH" not in source,
    "First-run setup initializes runtime secret": "FLASK_SECRET_KEY" in setup,
    "Contact defaults are configured": "sarinshabadofficial@gmail.com" in setup and "9878654329" in setup,
    "Product preview accepts PDF/video": "save_preview_upload" in source and "preview_type" in product,
    "Product page has email enquiry link": "mailto:{{ contact_email }}" in product,
    "Product page has call link": "tel:{{ contact_phone" in product,
    "Home page describes contact-to-buy": "contact us to discuss how to purchase it" in home,
    "Admin can manage products": "product_new" in admin and "product_edit" in admin,
    "Contact links appear globally": "mailto:{{ contact_email }}" in base and "tel:{{ contact_phone" in base,
    "Launcher creates venv": "-m venv .venv" in run_bat,
    "Launcher installs requirements": "pip install -r requirements.txt" in run_bat,
    "Readme explains manual contact sales": "does not take online payments" in readme,
}
for label, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {label}")
failed = [label for label, passed in checks.items() if not passed]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed.")
raise SystemExit(1 if failed else 0)
