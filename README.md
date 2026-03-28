# LabCab On-The-Go

A full-stack lab apparatus borrowing and monitoring system with role-based access, real-time inventory updates, notifications, and PDF receipts.

## Project Structure

- `backend/`
- `backend/app.py` Flask API (MongoDB)
- `backend/utils/pdf.py` PDF receipt generator
- `backend/requirements.txt` backend dependencies
- `frontend/`
- `frontend/index.html` UI
- `frontend/styles.css` styling
- `frontend/app.js` frontend logic

## Quick Start (Local)

### 1) Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
```

Set environment variables (PowerShell):

```powershell
$env:MONGO_URL="mongodb://localhost:27017"
$env:MONGO_DB="labcab"
$env:JWT_SECRET_KEY="change-me"
```

Run API:

```bash
python backend\app.py
```

The API will run on `http://127.0.0.1:5000`.

### 2) Frontend

Open `frontend/index.html` in a browser.

If deploying the frontend separately, set a global in `frontend/index.html` before `app.js` loads:

```html
<script>window.API_BASE = "https://your-render-service.onrender.com/api";</script>
```

## Render Deployment Notes

Set these environment variables in Render:

- `MONGO_URL` = your MongoDB connection string (e.g., MongoDB Atlas)
- `MONGO_DB` = `labcab`
- `JWT_SECRET_KEY` = a strong secret

The backend will auto-seed sample data on first run.

## Seeded Sample Accounts

- Admin: `admin@labcab.local` / `admin123`
- Borrower: `student@labcab.local` / `student123`

## Notes

- "Real-time" updates are handled via polling every 15 seconds.
- Status badges: `Available`, `Low Stock`, `In Use`.
- PDF receipts are available after a request is approved.

## API Routes

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/apparatus`
- `POST /api/apparatus` (admin)
- `POST /api/borrow-requests`
- `PATCH /api/borrow-requests/<id>` (admin approve/reject)
- `GET /api/borrow-records` (admin)
- `GET /api/borrow-records/me`
- `PATCH /api/borrow-records/<id>/return` (admin)
- `GET /api/borrow-records/<id>/receipt`
- `GET /api/notifications`
- `PATCH /api/notifications/<id>/read`
- `GET /api/dashboard/summary` (admin)

## Database Collections (MongoDB)

**users**

- `_id`
- `name`
- `email`
- `password_hash`
- `role`

**apparatus**

- `_id`
- `name`
- `total_quantity`
- `available_quantity`

**borrow_records**

- `_id`
- `user_id`
- `apparatus_id`
- `quantity`
- `borrow_date`
- `due_date`
- `status`
- `transaction_id`

**notifications**

- `_id`
- `user_id`
- `message`
- `status`
- `created_at`
