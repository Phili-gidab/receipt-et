// App URL: same-origin "/app" in production (FastAPI serves both);
// override for local dev via VITE_APP_URL=http://localhost:8010/app
export const APP = import.meta.env.VITE_APP_URL || "/app";
