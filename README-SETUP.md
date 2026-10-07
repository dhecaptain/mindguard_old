# MindGuard - Quick Start Guide

## Prerequisites

- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install/) installed
- [Git](https://git-scm.com/) installed

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/dhecaptain/mindguard_old.git
cd mindguard_old
```

### 2. Set Up Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Generate a secure JWT secret and add it to `.env`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` and set the following required values:

```env
JWT_SECRET=your_generated_secret_here
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_key
```

> **Note:** The application will automatically create demo accounts on first startup (when `MINDGUARD_ENV` is not set to `production`). See [Admin Access](#admin-access) below.

### 3. Run the Application with Docker (Recommended)

Build and start all services:

```bash
docker compose up --build -d
```

This will start:
- **Backend API**: Running in a container with the ML model
- **Frontend**: Served via Nginx
- **Data persistence**: Stored in Docker volumes

The build may take a few minutes on first run (downloading ML model weights and dependencies).

### 4. Access the Application

Once the containers are running:

- **Frontend**: [http://localhost](http://localhost) (or [http://localhost:80])
- **Backend Health Check**: [http://localhost:8000/api/v1/healthz](http://localhost:8000/api/v1/healthz)

## Admin Access

The application automatically seeds demo accounts on fresh database initialization (non-production environment):

| Role | Email | Password |
|---|---|---|
| Admin | `admin@mindguard.org` | `password` |
| Counsellor | `counsellor@mindguard.org` | `password` |
| Student | `student@mindguard.org` | `password` |
| Demo Counsellor | `demo@mindguard.org` | `password` |

> **Production Note:** In production (`MINDGUARD_ENV=production`), only the admin account is seeded and a random password is logged on first startup. Set `MINDGUARD_ADMIN_PASSWORD` in your `.env` to control it.

## Stopping the Application

```bash
docker compose down
```

To also remove all data volumes (reset database):

```bash
docker compose down -v
```

## Viewing Logs

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Frontend only
docker compose logs -f frontend
```

## Troubleshooting

- **Port conflicts**: If port 80 is already in use, change `FRONTEND_PORT` in `.env` (e.g., `FRONTEND_PORT=8080`), then access via `http://localhost:8080`.
- **Build issues**: If the build fails due to Hugging Face model download, add `HF_TOKEN` to `.env` if the model repository is private.
- **Health check failing**: Wait for the backend to fully initialize (ML model loading can take time). Check logs with `docker compose logs backend`.

