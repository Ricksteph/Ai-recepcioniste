/** @type {import('next').NextConfig} */
const API_URL = process.env.API_URL || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    // Proxy API calls to the FastAPI backend (avoids CORS in dev and prod).
    return [
      { source: "/api/:path*", destination: `${API_URL}/api/:path*` },
      { source: "/health", destination: `${API_URL}/health` },
      { source: "/widget.js", destination: `${API_URL}/widget.js` },
      { source: "/static/:path*", destination: `${API_URL}/static/:path*` },
    ];
  },
};

export default nextConfig;
