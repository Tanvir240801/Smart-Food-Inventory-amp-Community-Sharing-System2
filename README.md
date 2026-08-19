Student: Tanvir Hossain
ID: 223014179
Course: Web Programing (CSE3120)
Section: 1
Instructor: Nasir Uddin Ahmed

# FoodShare Inventory Web Application

A course open-ended web programming project for CSE 3120. The application helps users:
- register/login securely;
- create, read, update and delete food inventory records;
- track expiry dates dynamically;
- identify urgent/expired items;
- list surplus food for community sharing;
- claim an available sharing listing.

## Stack
- Python + Flask
- SQLite
- HTML5 + Bootstrap 5
- Jinja2 templates

## Run locally
1. Create a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Set a strong secret in production:
   `SECRET_KEY="your-long-random-secret"`
4. Run:
   `python app.py`
5. Open the local address shown by Flask.

The SQLite database is created automatically on first run.

## Security notes
- Passwords are stored as adaptive password hashes using Werkzeug's scrypt implementation.
- POST requests use a session-bound CSRF token.
- SQL statements use parameterized queries.
- Ownership checks prevent users from editing/deleting another user's inventory.
- SQLite foreign keys are enabled for each connection.
- For production deployment, use HTTPS and set `SESSION_COOKIE_SECURE=True`.
