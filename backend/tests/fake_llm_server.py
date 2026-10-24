"""Faux serveur OpenAI-compatible — vérification E2E de la bascule de quota.

Usage (dev uniquement) :  python tests/fake_llm_server.py   # port 8099

- model == "quota-model"  → HTTP 429 (quota dépassé)
- sinon                   → 200 avec une réponse JSON valide
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence
        pass

    def do_GET(self):
        """GET /v1/models — catalogue simulé pour tester l'expansion `provider:*`."""
        if self.path.rstrip("/").endswith("/models"):
            ids = ["quota-model", "broken-vision-embed-model", "works-model"]
            body = json.dumps({"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if payload.get("model") == "quota-model":
            body = json.dumps({"error": {"message": "rate limit exceeded", "code": 429}}).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        system = ""
        for m in payload.get("messages", []):
            if m.get("role") == "system":
                system += m.get("content", "")
        if "classification d'intentions" in system:
            content = json.dumps({"intent": "GREETING", "confidence": 0.95, "entities": {}})
        else:
            content = json.dumps(
                {
                    "reply": "[fallback-model] Bonjour ! Réponse générée après bascule de quota.",
                    "actions": [],
                    "escalate": False,
                    "need_info": [],
                }
            )
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": content}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
