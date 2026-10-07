"""Command-line admin for the college network. There is deliberately no web sign-up.

  python -m app.admin add-college "Demo Institute of Technology" DIT
  python -m app.admin add-officer --college DIT --name "Asha Rao" --email asha@dit.example
  python -m app.admin add-officer --admin --name "Network Admin" --email admin@example.org
  python -m app.admin reset-password --email asha@dit.example
  python -m app.admin list
"""

import argparse
import getpass
import secrets
import sqlite3
import sys

from app import auth, db


def add_college(name: str, code: str) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO colleges (name, code, created_at) VALUES (?, ?, ?)",
            (name.strip(), code.strip().upper(), db.now()),
        )
        return cur.lastrowid


def add_user(name: str, email: str, password: str, role: str = "officer", college_code: str | None = None) -> int:
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters.")
    if role == "officer" and not college_code:
        raise ValueError("An officer needs --college.")
    with db.connect() as conn:
        college_id = None
        if college_code:
            row = conn.execute("SELECT id FROM colleges WHERE code = ?", (college_code.upper(),)).fetchone()
            if not row:
                raise ValueError(f"No college with code {college_code}. Add it first with add-college.")
            college_id = row["id"]
        cur = conn.execute(
            "INSERT INTO users (college_id, role, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (college_id, role, name.strip(), email.strip().lower(), auth.hash_password(password), db.now()),
        )
        return cur.lastrowid


def set_password(email: str, password: str) -> None:
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters.")
    with db.connect() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                           (auth.hash_password(password), email.strip().lower()))
        if not cur.rowcount:
            raise ValueError(f"No user with email {email}.")
        # Log out everywhere after a password change.
        conn.execute("DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE email = ?)",
                     (email.strip().lower(),))


def _ask_password(generate: bool) -> str:
    if generate:
        password = secrets.token_urlsafe(12)
        print(f"Generated password (shown once, share it privately): {password}")
        return password
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords didn't match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="Manage the college network.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-college", help="Add a college")
    p.add_argument("name")
    p.add_argument("code", help="Short code students pick when reporting, e.g. DIT")

    p = sub.add_parser("add-officer", help="Add a placement officer (or --admin)")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--college", help="College code (required for officers)")
    p.add_argument("--admin", action="store_true", help="Network admin: sees every college")
    p.add_argument("--generate-password", action="store_true")

    p = sub.add_parser("reset-password", help="Set a new password for a user")
    p.add_argument("--email", required=True)
    p.add_argument("--generate-password", action="store_true")

    sub.add_parser("list", help="List colleges and users")

    args = parser.parse_args(argv)
    try:
        if args.command == "add-college":
            add_college(args.name, args.code)
            print(f"Added college {args.name} ({args.code.upper()}).")
        elif args.command == "add-officer":
            role = "admin" if args.admin else "officer"
            add_user(args.name, args.email, _ask_password(args.generate_password), role, args.college)
            print(f"Added {role} {args.email}.")
        elif args.command == "reset-password":
            set_password(args.email, _ask_password(args.generate_password))
            print(f"Password updated for {args.email}; their sessions were logged out.")
        elif args.command == "list":
            with db.connect() as conn:
                for c in conn.execute("SELECT code, name FROM colleges ORDER BY code"):
                    print(f"college  {c['code']:<8} {c['name']}")
                for u in conn.execute("""SELECT u.email, u.role, c.code FROM users u
                                         LEFT JOIN colleges c ON c.id = u.college_id ORDER BY u.email"""):
                    print(f"{u['role']:<8} {u['email']:<35} {u['code'] or '(all colleges)'}")
    except (ValueError, sqlite3.IntegrityError) as exc:
        message = "That college code or email already exists." if isinstance(exc, sqlite3.IntegrityError) else exc
        print(f"Error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
