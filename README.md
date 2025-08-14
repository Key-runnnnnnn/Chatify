# Chatify

Real-time multi-room chat application built with Flask, Flask-SocketIO, JWT (cookie-based auth), and MongoDB (with graceful in-memory fallback when a database is unavailable).

## ✨ Features

- User registration & login (passwords hashed with Werkzeug)
- JWT authentication stored in HttpOnly cookie
- Create, list, join, and delete chat rooms
- Secure room membership tracking
- Real-time messaging via Socket.IO
- Join/leave system notifications
- Kick users (room creator only)
- Fallback to in-memory storage if MongoDB not reachable (development convenience)
- Environment-driven configuration (.env)

## 🗂 Tech Stack

- Python / Flask
- Flask-SocketIO (WebSocket transport)
- Flask-JWT-Extended
- MongoDB (Atlas or local)
- Eventlet (async server for production)
- Gunicorn (optional production runner)
- python-dotenv

## 📁 Project Structure

```
Chatify/
├── app.py                # Main Flask & Socket.IO app
├── requirements.txt      # Python dependencies
├── templates/            # Jinja2 templates (auth, dashboard, chat UI)
└── utils/                # (Reserved for future helpers)
```

## 🔐 Authentication Model

- After successful login/registration a JWT access token is created and stored in an HttpOnly cookie (`access_token_cookie`).
- Protected routes use custom decorator `@jwt_required_cookie` which internally verifies the cookie.
- No refresh tokens yet (single access token only).

## 🔄 Room & Message Flow (High-Level)

1. Authenticated user creates a room → random URL-safe key generated.
2. Users join a room via its key.
3. Client emits `join` event → server adds Socket.IO room + broadcasts system message.
4. Messages (`message` event) broadcast to all connected members.
5. Room owner can emit `kick_user` to remove a member.

## 🧪 Socket.IO Events

| Event         | Direction | Payload (client → server) / (server → client) | Description                                         |
| ------------- | --------- | --------------------------------------------- | --------------------------------------------------- |
| `join`        | C → S     | `{ room: <room_key> }`                        | Adds user to room; server broadcasts system message |
| `leave`       | C → S     | `{ room: <room_key> }`                        | Removes user; system leave notice                   |
| `message`     | C → S     | `{ room: <room_key>, message: <text> }`       | Broadcasts chat message with username & timestamp   |
| `message`     | S → C     | `{ username, message, timestamp, user_id? }`  | Delivered to all room members                       |
| `kick_user`   | C → S     | `{ room: <room_key>, target_user_id }`        | Room creator only; triggers `user_kicked`           |
| `user_kicked` | S → C     | `{ kicked_user_id, message }`                 | Notifies room of a kicked user                      |

## 🌐 HTTP Routes

| Route                     | Methods  | Auth       | Purpose                         |
| ------------------------- | -------- | ---------- | ------------------------------- |
| `/`                       | GET      | Optional   | Redirects to login or dashboard |
| `/register`               | GET/POST | Public     | Create account + auto-login     |
| `/login`                  | GET/POST | Public     | User login                      |
| `/dashboard`              | GET      | JWT cookie | User landing page               |
| `/update_profile`         | POST     | JWT cookie | Update username/email/password  |
| `/my_rooms`               | GET      | JWT cookie | List rooms created by user      |
| `/create_room`            | POST     | JWT cookie | Create a new room               |
| `/join_room`              | GET/POST | JWT cookie | Join an existing room by key    |
| `/chat/<room_key>`        | GET      | JWT cookie | Chat UI for a room              |
| `/leave_room/<room_key>`  | GET      | JWT cookie | Leave a room                    |
| `/delete_room/<room_key>` | GET      | JWT cookie | Delete owned room               |
| `/logout`                 | GET      | Public     | Clear auth cookie               |

## ⚙️ Environment Variables (.env)

Create a `.env` file in the project root (values below are examples / defaults in code):

```
SECRET_KEY=change-me
JWT_SECRET_KEY=change-me-too
JWT_TOKEN_LOCATION=cookies
JWT_ACCESS_COOKIE_PATH=/
JWT_COOKIE_CSRF_PROTECT=False
JWT_ACCESS_COOKIE_NAME=access_token_cookie

# Database (Atlas preferred)
MONGODB_ATLAS_URI=mongodb+srv://<user>:<pass>@cluster0.mongodb.net/?retryWrites=true&w=majority
MONGODB_LOCAL_URI=mongodb://localhost:27017/
DATABASE_NAME=chatify_db
USERS_COLLECTION=users
ROOMS_COLLECTION=rooms

# CORS / Socket
CORS_ALLOWED_ORIGINS=*

# Server
HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=True
```

If both Atlas and local MongoDB are unreachable the app logs a warning and uses in-memory dicts (data lost on restart).

## 🛠 Local Development Setup

```bash
# 1. Clone & enter
git clone <your-fork-or-repo-url> Chatify
cd Chatify

# 2. Create virtual environment (Windows bash)
python -m venv .venv
source .venv/Scripts/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create .env
cp .env.example .env  # (Create one manually if file not present)

# 5. Run the dev server
python app.py

# 6. Open in browser
http://127.0.0.1:5000
```

## 🚀 Production (Example)

Use Gunicorn with Eventlet worker (single worker is usually fine for small real-time apps):

```bash
gunicorn -k eventlet -w 1 -b 0.0.0.0:8000 app:app
```

Or run via a Procfile (Heroku/Render):

```
web: gunicorn -k eventlet -w 1 -b 0.0.0.0:$PORT app:app
```

Make sure environment variables are configured in your hosting platform.

## 🔒 Security Notes

- JWT stored in HttpOnly cookie reduces XSS token theft risk.
- CSRF protection for cookies is disabled by default (`JWT_COOKIE_CSRF_PROTECT=False`); enable it in production.
- No rate limiting implemented yet (consider Flask-Limiter).
- Password reset / email verification not implemented.

## 🧭 Possible Improvements

- Add frontend assets bundling & styling polish
- Implement refresh tokens & token revocation
- Add message persistence (current code does not store chat logs)
- Add room moderation actions (mute / ban)
- Add unit/integration tests
- Add typing (mypy / type hints) & linting (ruff/flake8)
- Implement pagination for rooms & members

## 🧪 Quick Smoke Test After Setup

1. Register a user.
2. Create a room (copy the generated key if displayed in UI / list page).
3. Open a second browser (or incognito), register/login, join the room via key.
4. Exchange messages; watch join/leave system messages.
5. As creator, kick the other user (if UI exposes that action) and observe `user_kicked` broadcast.

## ❓ Troubleshooting

| Issue                           | Cause                  | Fix                                           |
| ------------------------------- | ---------------------- | --------------------------------------------- |
| MongoDB Atlas connection failed | Invalid URI / network  | Verify `MONGODB_ATLAS_URI` & IP allowlist     |
| Falls back to in-memory storage | DB unavailable         | Start MongoDB or fix URI                      |
| Socket events not firing        | Wrong origins / CORS   | Set `CORS_ALLOWED_ORIGINS=*` or proper domain |
| 401 redirect to login           | Missing/expired cookie | Re-login; check cookie blocked by browser     |
| Gunicorn hang / no websockets   | Wrong worker class     | Use `-k eventlet`                             |

## 📝 License

Add your chosen license (e.g., MIT) here. Example:

```
MIT License © 2025 Your Name
```

## 🙌 Contributing

1. Fork the repo
2. Create feature branch: `git checkout -b feat/awesome`
3. Commit: `git commit -m "feat: add awesome"`
4. Push: `git push origin feat/awesome`
5. Open Pull Request

## 📣 Acknowledgements

- Flask & Flask-SocketIO maintainers
- MongoDB team
- Open-source community

---

Happy chatting! 🎉
