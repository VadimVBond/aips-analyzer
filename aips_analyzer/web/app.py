"""
AIPS Analyzer Web UI — Flask application.

Usage:
    aips-web                      # default port 5000
    aips-web --port 8080
    python -m aips_analyzer.web
    flask --app aips_analyzer.web.app run
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from flask import Flask


def _get_template_dir() -> Path:
    return Path(__file__).parent / "templates"


def create_app(template_dir: Path | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(template_dir or _get_template_dir()),
    )
    app.config["AIPS_OUTPUT_DIR"] = os.environ.get(
        "AIPS_OUTPUT_DIR", str(Path.cwd() / "output")
    )

    # Register routes
    from . import routes

    app.register_blueprint(routes.bp)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aips-web",
        description="AIPS Analyzer Web UI — local analysis dashboard",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind to (default: 5000)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to read analysis packages from (default: ./output)",
    )
    args = parser.parse_args()

    app = create_app()
    if args.output_dir:
        app.config["AIPS_OUTPUT_DIR"] = str(Path(args.output_dir).resolve())

    print(f"\n  AIPS Analyzer Web UI  v0.1.0")
    print(f"  http://{args.host}:{args.port}")
    print()
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()
