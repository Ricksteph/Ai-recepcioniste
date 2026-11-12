/** @type {import('next').NextConfig} */
const API_URL = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    // Proxy API calls to the FastAPI backend (avoids CORS in dev and prod).
    return [
      // /api/* est relayé par app/api/[...path]/route.ts : les rewrites du
      // serveur de dev coupent au bout de 30 s, trop court pour un message
      // qui parcourt la chaîne de repli LLM.
      { source: "/health", destination: `${API_URL}/health` },
      { source: "/widget.js", destination: `${API_URL}/widget.js` },
      { source: "/static/:path*", destination: `${API_URL}/static/:path*` },
    ];
  },
};

export default nextConfig;
