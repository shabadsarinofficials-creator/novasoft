"""Create runtime configuration; first admin account is configured in the browser."""
from pathlib import Path
import secrets
ROOT=Path(__file__).resolve().parent
ENV_PATH=ROOT/".env"
DEFAULTS={"STORE_NAME":"NovaSoft","APP_ENV":"development","FLASK_SECRET_KEY":secrets.token_urlsafe(48),"CONTACT_EMAIL":"sarinshabadofficial@gmail.com","CONTACT_PHONE":"9878654329","DATABASE_URL":"sqlite:///novasoft.db","COOKIE_SECURE":"false","MAX_UPLOAD_MB":"500","STORAGE_DIR":"storage","PORT":"5000"}
def main():
    if ENV_PATH.exists():
        lines=ENV_PATH.read_text(encoding="utf-8").splitlines(); keys={x.split("=",1)[0] for x in lines if "=" in x}; additions=[(k,v) for k,v in DEFAULTS.items() if k not in keys]
        if additions:
            with ENV_PATH.open("a",encoding="utf-8") as f:
                if lines and lines[-1].strip(): f.write("\n")
                for k,v in additions: f.write(f"{k}={v}\n")
        print("Existing settings preserved.")
    else:
        ENV_PATH.write_text("# Private NovaSoft runtime configuration. Do not share.\n"+"".join(f"{k}={v}\n" for k,v in DEFAULTS.items()),encoding="utf-8"); print("Runtime configuration created.")
    try: ENV_PATH.chmod(0o600)
    except OSError: pass
    print("Create the admin username and password in the browser on first launch.")
    return 0
if __name__=="__main__": raise SystemExit(main())
