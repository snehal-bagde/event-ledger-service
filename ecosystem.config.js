module.exports = {
  apps: [
    {
      name: "event-ledger",
      script: ".venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000 --workers 2",
      cwd: "/srv/event-ledger",
      interpreter: "none",
      autorestart: true,
      watch: false,
      env: {
        APP_ENV: "production",
      },
    },
  ],
};
