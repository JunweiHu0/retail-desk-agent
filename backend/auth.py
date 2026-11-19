"""Password authentication with hashed credentials and revocable HttpOnly sessions."""

import hashlib
import hmac
import secrets
import time
import uuid

from backend.store import now

DEMO_PASSWORD = "Demo@Retail2026!"
SESSION_TTL = 12 * 60 * 60
ITERATIONS = 600_000


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def password_matches(password, encoded):
    try:
        _, iterations, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, store, demo_enabled=True):
        self.store = store
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))
        with store.tx() as cx:
            cx.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES accounts(user_id)
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    key TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start INTEGER NOT NULL
                );
            """)
            if demo_enabled:
                for user in store.dataset(cx)["users"].values():
                    if user["user_id"].startswith("demo_") and user["email"].endswith(
                        "@retail-demo.example.com"
                    ):
                        if not cx.execute(
                            "SELECT 1 FROM accounts WHERE user_id=?", (user["user_id"],)
                        ).fetchone():
                            cx.execute(
                                "INSERT INTO accounts VALUES(?,?,?,?)",
                                (
                                    user["user_id"],
                                    user["email"].casefold(),
                                    password_hash(DEMO_PASSWORD),
                                    now(),
                                ),
                            )

    def provision_for_existing(self, uid, password):
        """Local administrator/test helper; not exposed as an HTTP account-claim route."""
        with self.store.tx() as cx:
            user = self.store.dataset(cx)["users"][uid]
            cx.execute(
                "INSERT INTO accounts VALUES(?,?,?,?)",
                (uid, user["email"].casefold(), password_hash(password), now()),
            )

    def login(self, email, password, client):
        email = email.strip().casefold()
        attempt_key = token_hash(client + ":" + email)
        stamp = int(time.time())
        with self.store.tx() as cx:
            attempt = cx.execute(
                "SELECT * FROM login_attempts WHERE key=?", (attempt_key,)
            ).fetchone()
            if attempt and stamp - attempt["window_start"] < 900 and attempt["failures"] >= 10:
                raise TimeoutError("登录尝试过多，请 15 分钟后再试。")
            row = cx.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
            valid = password_matches(password, row["password_hash"] if row else self.dummy_hash)
            if not row or not valid:
                if not attempt or stamp - attempt["window_start"] >= 900:
                    cx.execute(
                        "INSERT OR REPLACE INTO login_attempts VALUES(?,1,?)", (attempt_key, stamp)
                    )
                else:
                    cx.execute(
                        "UPDATE login_attempts SET failures=failures+1 WHERE key=?", (attempt_key,)
                    )
                failure = True
            else:
                cx.execute("DELETE FROM login_attempts WHERE key=?", (attempt_key,))
                token = secrets.token_urlsafe(32)
                cx.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (stamp,))
                cx.execute(
                    "INSERT INTO auth_sessions VALUES(?,?,?,?)",
                    (token_hash(token), row["user_id"], stamp + SESSION_TTL, now()),
                )
                uid, failure = row["user_id"], False
        if failure:
            raise PermissionError("邮箱或密码不正确。")
        return token, uid

    def current(self, token):
        if not token or len(token) > 256:
            return None
        with self.store.tx() as cx:
            row = cx.execute(
                "SELECT user_id FROM auth_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(token), int(time.time())),
            ).fetchone()
            return row["user_id"] if row else None

    def logout(self, token):
        if token:
            with self.store.tx() as cx:
                cx.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash(token),))

    def register(self, email, password, first_name, last_name):
        email = email.strip().casefold()
        uid = "customer_" + uuid.uuid4().hex[:16]
        with self.store.tx() as cx:
            data = self.store.dataset(cx)
            if any(u["email"].strip().casefold() == email for u in data["users"].values()):
                raise ValueError("该邮箱已存在，不能通过注册接管已有账户。")
            data["users"][uid] = {
                "user_id": uid,
                "email": email,
                "name": {"first_name": first_name, "last_name": last_name},
                "address": {
                    key: "" for key in ("address1", "address2", "city", "state", "country", "zip")
                },
                "payment_methods": {},
                "orders": [],
            }
            cx.execute(
                "INSERT INTO accounts VALUES(?,?,?,?)", (uid, email, password_hash(password), now())
            )
            self.store.save_dataset(cx, data)
        return uid
